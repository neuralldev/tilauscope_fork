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
# TiLau 2025, 2026

import logging
from dataclasses import dataclass
from typing import Final, Any
from fpdf import FPDF, XPos, YPos
import json
import ast
import copy
import math
from pathlib import Path, PosixPath
import re
import numpy as np

from tilauscope.tilauscope_types import AGTRON_SCALES, AgtronScale, ProbeDeviation, RoasterBasicPlan, RoasterBasicPlanPerPhase, GreenBean, RoastingPhase, get_ror_ideal_band, to_agtron
from tilauscope.roasters import RoasterContext
from tilauscope.bean_energy import Ambient, BeanProps, FloorProfile, maillard_floor
from artisanlib.atypes import ProfileData
from artisanlib.util import cast, fromCtoFstrict
from PyQt6.QtCore import  QSettings
from PyQt6.QtWidgets import QApplication

from artisanlib.util import convertTemp, convertWeight, fromFtoCstrict, fill_gaps, events_internal_to_external_value, smooth_list  ## TILAU ## smooth_list moved from tgraphcanvas to util

_logd: Final[logging.Logger] = logging.getLogger('tilau')

## Le feu de séchage est TENU jusqu'à ce délai avant le DRY END. Doctrine Tilau :
## le réglage de séchage vient du setup et ne se touche pas avant ~30 s du DE.
_HOLD_LEAD_SEC: Final[float] = 30.0

## Part du séchage dans le total. Pratique standard : le séchage fait environ la
## moitié du roast. Constante de MODULE : la durée de base et le plancher de la
## branche « eau libre » la lisent toutes les deux — deux copies locales
## finiraient par diverger sans que rien n'échoue.
_DRY_SHARE: Final[float] = 0.50

## La Dev Ramp part du palier pre-FC et ne descend jamais de plus de
## _DEV_BURNER_DROP_CAP sous lui (le feu se TIENT en développement). Constante
## de MODULE : le résumé de phase (généré après l'escalier) et la Dev Ramp
## elle-même la lisent toutes les deux.
_DEV_BURNER_DROP_CAP: Final[float] = 6.0

## Charge temperature bands, in MEASURED BT (what the probe displays, no offset
## applied). Standard roasting practice: the green-coffee process sets the band;
## bean and ambient constants only modulate a few degrees inside it. The target
## roast level does NOT move the charge — it is expressed in the phase timings
## and the heater ladder instead.
_CHARGE_BAND_BY_PROCESS: dict[str, tuple[float, float]] = {
    "washed":  (180.0, 190.0),
    "natural": (170.0, 180.0),
    "decaf":   (160.0, 170.0),
}
_CHARGE_MODULATION_MAX_C: float = 5.0


def _clamp(value: float, between_min: float, between_max: float) -> float:
    return max(between_min, min(between_max, value))

def _mean(low:float, high:float) -> float:
    return (low + high) * 0.5

def heat_soak_correction(minutes_since_drop: float, thermal_mass: float,
                         heat_retention: float) -> tuple[float, int, float]:
    """
    Correction back-to-back (°C interne) — modèle validé 2026-07-04.

    Au batch 2+, le fût gorgé de chaleur rend la même BT de charge plus
    énergétique : on charge plus bas et on part burner réduit, avec une
    décroissance exponentielle sur le temps d'attente depuis le DROP :

        soak    = exp(−Δt / τ),  τ = 12 + 30 × moy(thermal_mass, heat_retention)  [min]
        Δcharge = −(4 + 6 × moy) × soak   [°C, plancher −10]
        Δheater = −round(5 × soak)        [%]

    Skywalker ≈ (τ 25 min, −6 °C max) ; fût fonte ≈ (τ 40 min, −9 °C max).
    Sous 5 % de soak la correction est nulle (machine considérée neutre).
    Retourne (delta_charge_c ≤ 0, delta_heater_pct ≤ 0, tau_min). Consommé par
    generate_roast_plan et par la reco d'attente de la page cooling.
    """
    mr = max(0.0, min(1.0, (thermal_mass + heat_retention) / 2.0))
    tau = 12.0 + 30.0 * mr
    soak = math.exp(-max(0.0, minutes_since_drop) / tau)
    if soak < 0.05:
        return 0.0, 0, tau
    dcharge = max(-10.0, -(4.0 + 6.0 * mr) * soak)
    dheater = -int(round(5.0 * soak))
    return dcharge, dheater, tau

@dataclass(frozen=True)
class _WaterActivityEffect:
    """Deltas from a GreenBean.water_activity reading, to be added to the
    in-progress plan variables; zero-valued when WA is unmeasured or neutral."""
    d_dry_time_min:   float = 0.0
    d_heater_dry_pct: float = 0.0
    d_airflow_pct:    float = 0.0
    d_extraction_pct: float = 0.0
    d_charge_c:       float = 0.0

@dataclass(frozen=True)
class _PhaseDurationCalibration:
    """Result of the cross-roast timing calibration and the physical duration
    floors that follow it (banc 2026-08-05): the final drying/Maillard
    durations, where they came from, the two calibration heater nudges, and
    the operator notes for the caller to append to history["actions"]."""
    dry_time_min:       float
    maillard_time_min:  float
    timing_source:      str
    cal_heater_dry_pct: float
    cal_heater_mai_pct: float
    notes: "list[str]"

@dataclass(frozen=True)
class _ChargeSetup:
    """Charge band by process, bean/ambient modulation (capped), and
    inter-batch heat-soak correction (banc 2026-08-05).

    `band` and `nominal_temperature_c` (the pre-modulation band midpoint)
    are still needed by the caller after this stage returns: `band` for the
    water-activity floor further down, `nominal_temperature_c` for the FC
    regression, which the original code interleaves between the band and
    the modulation. `temperature_c` is the final charge BT, after
    modulation and heat soak."""
    band: "tuple[float, float]"
    nominal_temperature_c: float
    temperature_c: float
    soak_dcharge_c: float = 0.0
    soak_dheater_pct: int = 0
    soak_tau_min: float = 0.0

@dataclass(frozen=True)
class _DropAndDevRor:
    """Learned-drop adoption from measured colours, the FC→DROP coherence
    rebuild, and the development/drop RoR derivation (banc 2026-08-05): the
    final drop BT and its source, the development RoR, the RoR at drop and
    its source, and the operator notes for the caller to append to
    history["actions"]."""
    drop_bt_temperature: float
    drop_source: str
    dev_ror: float
    drop_ror: float
    drop_ror_source: str
    notes: "list[str]"

@dataclass(frozen=True)
class _BurnerSetpoints:
    """Grid/learned burner setpoints for dry/Maillard/dev, the Maillard energy
    floor, and the learned pre-FC setpoint (banc 2026-08-05).

    `floor` and `heater_max_pct` are still needed by the caller after this
    stage returns: `floor` for the anticipated heater ramp and the Dev Ramp
    further down, `heater_max_pct` as the clamp ceiling for every later
    burner adjustment (pre-DE gesture, Dev Ramp coherence, heater ramp).
    `dev_free_pct` is the pre-floor development setpoint (the original
    code's `_h_dev_free`), still needed by the caller's Dev Ramp coherence
    recalculation to detect whether that later step raised heater_dev
    further. `heater_tp` is derived here (it only depends on heater_dry and
    is_light_roast) even though the original code computed it inline right
    after the floor — grouping it with the setpoints it derives from is the
    point of this stage."""
    heater_dry: float
    heater_maillard: float
    heater_dev: float
    heater_pre_fc: float
    heater_tp: float
    heater_source: str
    heater_fc_source: str
    floor: FloorProfile
    heater_max_pct: float
    dev_free_pct: float
    notes: "list[str]"

@dataclass(frozen=True)
class _HeaterRamp:
    """Anticipated heater ramp geometry (BT-anchored pre-FC anchor, Dev Ramp
    coherence), the learned pre-dry-end anti-flick gesture, and the built
    heater ramp itself (banc 2026-08-05).

    `pre_fc_c` (the original code's `_pre_fc_c`) is still needed by the
    caller after this stage returns: the airflow ramp further down anchors
    its own pre-FC BT waypoint on it. `heater` is the formatted
    [dry%, mai%, dev%] summary list — built AFTER the Dev Ramp coherence
    adjustment raises heater_dev, so it never publishes a development power
    the ramp doesn't hold. `heater_pre_de`, `pre_de_active`, `de_lead_sec`
    and `de_step_pct` are the learned pre-dry-end gesture, still needed by
    the caller's plan summary dict and re-plan context."""
    heater_pre_fc: float
    heater_dev: float
    heater: "list[str]"
    heater_ramp: "list[dict]"
    fc_anticipation_sec: float
    pre_fc_c: float
    heater_pre_de: float
    pre_de_active: bool
    de_lead_sec: float
    de_step_pct: float
    notes: "list[str]"

@dataclass(frozen=True)
class _DrumSpeed:
    """Drum speed — UNE valeur de SETUP (item B, Bench-Integration), banc
    2026-08-05: chosen once at charge from batch weight and density, then
    held for all three phases (never an in-roast drum gesture — see the
    doctrine comment inside the method). Returns the [dry, mai, dev] drum
    percentage list, identical across the three columns, or the "--" skip
    marker on machines without a variable-speed drum."""
    drum_speed_pct: "list[str]"

@dataclass(frozen=True)
class _AirflowExtraction:
    """Airflow/extraction base values (roaster airflow-dependency-scaled),
    the shared learned-trajectory helper, the Maillard Air Ramp and the
    Development Ramp (banc 2026-08-05) — see the method for the doctrine
    comments (airflow supports the thermal reaction on this machine, the
    Maillard ramp opening only ~40% of the total rise, the development
    ramp's burner-hold/air-support coupling).

    `airflow`, `extraction` and `airwave_mode` are the formatted [dry, mai,
    dev] summary lists (extraction/airwave_mode reflect the AirWave
    recommendation when present, overriding the computed extraction
    values). `air_ramp` and `dev_ramp` are the BT-anchored step lists;
    `dev_ramp_source` records whether the Dev Ramp target came from learned
    history or the default column."""
    airflow: "list[str]"
    extraction: "list[str]"
    airwave_mode: "list[str]"
    air_ramp: "list[dict]"
    dev_ramp: "list[dict]"
    dev_ramp_source: str

@dataclass(frozen=True)
class _PlanConfidence:
    """Plan confidence & its adaptive tolerance factor, and the heat-soak
    back-to-back operator note (design validé 2026-07-04 for the confidence
    scoring, banc 2026-08-05 for the extraction).

    `level` and `tol_factor` feed both the coach's relative RoR bands and
    the EOR adherence bilan further down; `display` is the operator-facing
    string (PDF, tooltips); `soak_note` is appended to history["actions"]
    by the caller, exactly like the other stages' notes."""
    level: str
    tol_factor: float
    display: str
    soak_note: "str | None"

class TilauScopeRoastPlan:
    def __init__(self, parent=None, roaster_ctx: RoasterContext |None = None):

        self.phases = ["UNKNOWN","DRY","MAILLARD","DEVELOPMENT"]

        self.alog_directory:str=""
        settings = QSettings()
        self.alog_directory = Path(settings.value('alogDirectory', "", str))
        self.parent = parent
        self.mode = "C"  # ← safe default; overwritten below if Artisan is available
        # parent IS the ApplicationWindow (aw); its temperature unit lives on aw.qmc.mode.
        # The previous `self.parent.aw.qmc` dereference never resolved (ApplicationWindow
        # has no `.aw`), so self.mode silently stayed "C" and every °F install got a plan
        # computed in °C numbers. Read qmc.mode directly, like all other accesses below.
        if hasattr(self.parent, 'qmc') and self.parent.qmc:
            self.mode = self.parent.qmc.mode  # 'C' or 'F', live from Artisan

        # ── Roaster context — single source of truth for machine-specific maths ──
        # Loaded via RoasterManager so the plan never hard-codes machine constants.
        self._roaster_ctx = roaster_ctx

        # ── Historical-analysis memoisation ──────────────────────────────────
        # _analyze_historical_roasts scans every .alog (uuid match + full parse)
        # — expensive, and it only depends on (bean, colour target, charge
        # weight), NOT on ambient conditions. Ambient-triggered plan
        # regenerations during PREHEAT/DRY therefore hit this cache instead of
        # re-reading the log directory on the UI thread. Scoped to this
        # instance's lifetime (a roast session): new alogs only appear after
        # DROP, when no regeneration can happen anymore.
        self._history_cache: dict[tuple, dict | None] = {}
        
    def _list_alogs(self):
        if not self.alog_directory or not Path(self.alog_directory).is_dir():
            return []
        return [f for f in Path(self.alog_directory).iterdir() if f.is_file() and f.suffix == '.alog']

    def _clean_delta_bt(self, delta_bt: list) -> list:
        """
        Fills None values in the delta_bt array.
        Uses forward-fill logic: replaces None with the last valid float.
        Initializes with 0 if None is found at the start of the list.
        """
        cleaned_list = []
        last_valid_value = 0.0  # Default value for the start of the roast

        for value in delta_bt:
            if value is None:
                cleaned_list.append(last_valid_value)
            else:
                # Ensure the value is a float for mathematical processing
                current_val = float(value)
                cleaned_list.append(current_val)
                last_valid_value = current_val
                
        return cleaned_list
    
    def _estimate_dt(self, timex) -> float:
        """Median sampling interval (s) of a log, derived from its own recorded
        timestamps. Robust to the user's Artisan sampling setting (qmc.delay),
        which varies per recording (see sampling.py). Falls back to 1.0 s."""
        tx = np.asarray(timex, dtype=float)
        if tx.size < 2:
            return 1.0
        d = np.diff(tx)
        d = d[d > 0]
        if d.size == 0:
            return 1.0
        return float(np.clip(np.median(d), 0.25, 10.0))

    def _find_turning_point_index(self, bt_input: list, dt: float = 1.0) -> int:
        """
        Index of the Turning Point = the BT minimum (where RoR crosses zero),
        searched in the early window (~15 s .. 2 min 30 after charge).

        NOTE: this uses BT, not the RoR minimum. The RoR minimum is the moment of
        steepest cooling, which occurs BEFORE the turning point; using it (as the
        previous implementation did) mislocated the TP systematically. Window
        bounds are converted from seconds to samples via the per-log dt.
        """
        bt = np.array([np.nan if b is None else float(b) for b in bt_input], dtype=float) if bt_input else np.array([])
        if bt.size == 0:
            return 0
        lo = min(int(round(15.0 / dt)), bt.size - 1)    # skip the charge instant
        hi = min(int(round(150.0 / dt)), bt.size)
        if hi <= lo:
            hi = bt.size
        if hi <= lo:
            return 0
        seg = bt[lo:hi]
        if np.all(np.isnan(seg)):
            return lo
        return lo + int(np.nanargmin(seg))

    def evaldeltas(self, data: dict, deltaname:str):
        tx = np.array(data.get("timex", []))
        timeindex = data.get("timeindex", [])
        rd = timeindex[RoastingPhase.CHARGE] if timeindex and timeindex[RoastingPhase.CHARGE] != -1 else 0
        drop = timeindex[RoastingPhase.DROP] if timeindex  else 0
        # Artisan alogs store their unit under "mode" ("temp_unit" never exists,
        # so the old read silently assumed every log was °C — a °F log was
        # converted twice on a °F install).
        unit = data.get("mode", "C")
        temp = [convertTemp(t,unit,self.parent.qmc.mode) for t in data.get(deltaname, [])]
                             
        cf = self.parent.qmc.curvefilter #*2 # we smooth twice as heavy for PID/RoR calculation as for normal curve smoothing
        t1 = smooth_list(data.get("timex", []),(fill_gaps(temp) if self.parent.qmc.interpolateDropsflag else temp),window_len=cf,decay_smoothing=not self.parent.qmc.optimalSmoothing)
        if len(t1)>10 and len(tx) > 10:
            # we start RoR computation 10 readings after CHARGE to avoid this initial peak
            RoR_start = min(rd+10,len(tx)-1)
            _, deltas = self.parent.qmc.recomputeDeltas(tx,RoR_start,drop,None,t1,optimalSmoothing=self.parent.qmc.optimalSmoothing)
            return deltas
        return None

    def _get_delta_bt(self, file_name: str):
        with open(file=Path(self.alog_directory) / file_name, encoding="utf-8") as f:
            content = f.read()
        self.lastprofiledata = cast('ProfileData', ast.literal_eval(content))
        ti = self.lastprofiledata.get("timeindex", [])
        if len(ti) == 0 or ti[RoastingPhase.CHARGE] == -1 or ti[RoastingPhase.DROP] == -1:
            return None, None, None, None, None

        start = ti[RoastingPhase.CHARGE]
        end   = ti[RoastingPhase.DROP]
        tx    = self.lastprofiledata.get("timex", [])

        # Timestamp de référence (charge = t=0)
        charge_ts = tx[start]

        # timex shifté : toutes les valeurs sont relatives à charge, en secondes
        timex_shifted = [(ts - charge_ts) for ts in tx]

        # Timestamps absolus des phases clés (en secondes depuis charge)
        # Utilisés par _which_phase — plus besoin d'indexer tx[ti[x]]
        phase_times = {
            "dry_end":  timex_shifted[ti[RoastingPhase.DRYEND]]  if ti[RoastingPhase.DRYEND]  > 0 else None,
            "fc_start": timex_shifted[ti[RoastingPhase.FCSTART]] if ti[RoastingPhase.FCSTART] > 0 else None,
            "drop":     timex_shifted[ti[RoastingPhase.DROP]],
        }

        delta_bt_input = self._clean_delta_bt(self.evaldeltas(self.lastprofiledata, "temp2"))
        bt_input       = self.lastprofiledata.get("temp2", [])
        # Align the BT series on the CURRENT display unit, like evaldeltas does
        # for the RoR series — otherwise the master curve mixes log units.
        _log_mode = str(self.lastprofiledata.get("mode", "C"))
        _cur_mode = (self.parent.qmc.mode
                     if self.parent is not None and getattr(self.parent, "qmc", None) is not None
                     else "C")
        if _log_mode != _cur_mode:
            bt_input = [convertTemp(t, _log_mode, _cur_mode) for t in bt_input]

        # Per-log sampling interval (s) derived from recorded timestamps -- robust to
        # the user's Artisan sampling setting (qmc.delay), which varies per log.
        dt = self._estimate_dt(timex_shifted[start:end])
        # TP = BT minimum (NOT the RoR minimum). Reverts the earlier mis-"fix" that
        # passed delta_bt; the RoR minimum is the steepest-cooling point, before TP.
        tp_index = self._find_turning_point_index(bt_input[start:end], dt)

        return (
            delta_bt_input[start:end],
            timex_shifted[start:end],
            bt_input[start:end],
            tp_index,
            phase_times,         # remplace ti_shifted
        )
     
    def _find_flicks_crashes(
                self,
                delta_bt: list,
                timex: list,
                phase_times: dict,
                tp_index: int,
                prominence: float = 1.0,        # degrees C/min: significance of the dip/bump
                debounce_sec: float = 20.0,
                recovery_margin_sec: float = 30.0,
        ):
        """
        Detect significant RoR dips (crashes) and bumps (flicks) as LOCAL EXTREMA
        ranked by PROMINENCE (degrees C/min).

        Why prominence: a healthy roast has a continuously declining RoR, which has
        no local extremum, so it is never flagged. A crash is a genuine local valley
        and a flick a genuine local peak; their prominence is the physical measure of
        how significant the event is, comparable across roasts.

        Sample-rate invariant: every time window/limit is converted to samples using
        the per-log sampling interval derived from timex, so detection no longer
        assumes 1 Hz.
        """
        from scipy.signal import find_peaks

        flicks: list = []
        crashes: list = []

        ror = np.asarray(self._clean_delta_bt(delta_bt), dtype=float)
        tx  = np.asarray(timex, dtype=float)
        n = ror.size
        if n < 10 or tx.size != n:
            return flicks, crashes

        dt = self._estimate_dt(tx)
        distance = max(1, int(round(debounce_sec / dt)))

        # Light denoise (~5 s). Prominence already rejects small wiggles, so keep
        # this light to avoid attenuating short real flicks near first crack.
        win = max(1, int(round(5.0 / dt)))
        if win > 1:
            kernel = np.ones(win) / win
            ror_s = np.convolve(ror, kernel, mode='same')
        else:
            ror_s = ror

        # Exclude the post-TP recovery: locate the recovery RoR peak within ~180 s
        # after the (BT-based) turning point, then start detecting a margin later so
        # the recovery peak itself is never mistaken for a flick.
        peak_limit = min(n, tp_index + int(round(180.0 / dt)))
        if 0 <= tp_index < peak_limit:
            rec_idx = tp_index + int(np.argmax(ror_s[tp_index:peak_limit]))
            detect_from_t = tx[rec_idx] + recovery_margin_sec
        else:
            detect_from_t = float(tx[0]) + 120.0

        flick_idx, fprops = find_peaks(ror_s, prominence=prominence, distance=distance)
        crash_idx, cprops = find_peaks(-ror_s, prominence=prominence, distance=distance)

        for k, i in enumerate(flick_idx):
            if tx[i] <= detect_from_t:
                continue
            flicks.append({
                "time":      float(tx[i]),
                "ror_value": round(float(ror_s[i]), 2),
                "severity":  round(float(fprops["prominences"][k]), 2),  # prominence, C/min
                "phase":     self._which_phase(float(tx[i]), phase_times),
            })
        for k, i in enumerate(crash_idx):
            if tx[i] <= detect_from_t:
                continue
            crashes.append({
                "time":      float(tx[i]),
                "ror_value": round(float(ror_s[i]), 2),
                "severity":  round(float(cprops["prominences"][k]), 2),  # prominence, C/min
                "phase":     self._which_phase(float(tx[i]), phase_times),
            })
        return flicks, crashes

    def _find_relevant_logs(self, target_bean_name: str, historical_logs: list[PosixPath]) -> list:
        """
        Finds historical logs using a fuzzy/partial match on both filenames 
        and internal bean metadata.
        """
        # Normalize the target: lowercase and remove non-alphanumeric (except spaces)
        target_clean = re.sub(r'[^a-zA-Z0-9 ]', '', target_bean_name.lower()).strip()
        target_parts = set(target_clean.split())

        # Empty / punctuation-only bean name → no searchable token. Bail out before
        # the 70% overlap test below, which divides by len(target_parts).
        if not target_parts:
            return []

        matches = []
        
        for log in historical_logs:
            # 1. Get searchable strings (filename and internal name if available)
            # Note: 'name' attribute exists in GreenBean dataclass
            file_name = log.name.lower()            
            combined_clean = re.sub(r'[^a-zA-Z0-9 ]', '', file_name)
            
            # 2. Check for exact containment
            if target_clean in combined_clean:
                matches.append(log)
                continue
                
            # 3. Check for partial overlap (e.g., "Ethiopia Yirgacheffe" matches "Ethiopia")
            # Useful if the user just searches for the region or country.
            found_parts = [part for part in target_parts if part in combined_clean]
            if len(found_parts) / len(target_parts) >= 0.7: # 70% match threshold
                matches.append(log)

        return matches

    def _find_logs_by_uuid(self, bean_uuid: str, historical_logs: list[PosixPath]) -> list:
        """
        Match alogs whose 'beans' field carries this BeanCave uuid
        (RoastSetup writes 'uuid: <uuid4>' into qmc.beans, saved in the .alog).

        Raw substring scan — no full parse: a uuid4 string is unique enough
        that a hit anywhere in the file identifies the bean. This is exact
        bean identity, unlike the fuzzy filename matching which confuses
        different lots of the same origin.
        """
        if not bean_uuid:
            return []
        needle = bean_uuid.lower()
        matches = []
        for log in historical_logs:
            try:
                with open(log, encoding="utf-8") as f:
                    if needle in f.read().lower():
                        matches.append(log)
            except OSError:
                continue
        return matches

    def _average_event_group(self, group):
        """
        Helper to average time and values for a cluster of detections 
        and identify the most common roasting phase for the event.
        """
        count = len(group)
        avg_time = sum(item['time'] for item in group) / count
        avg_ror = sum(item['ror_value'] for item in group) / count
        avg_sev = sum(item['severity'] for item in group) / count
        
        phases= (item['phase'] for item in group)
        counts = {}
        for p in phases:
            if p != 0:
                counts[p] = counts.get(p, 0) + 1        

        if counts:
            most_present = max(counts, key=counts.get)
        else:
            return None   

        phase_label = self.phases[most_present]

        return {
            "time": round(avg_time, 1),
            "ror_value": round(avg_ror, 2),
            "severity": round(avg_sev, 2),
            "occurrence_count": count,
            "phase": phase_label
        }

    def _average_color_in_agtron(self, color: float, color_system: str) -> float:
        """Convert a color reading to the Agtron scale via the single shared
        converter (tilauscope_types.to_agtron) so every module agrees."""
        return to_agtron(color, color_system)

    _BURNER_ETYPE: Final = 3   # etypes = [Air, Drum, Damper, Burner]

    def _burner_events(self, data: dict, charge_ts: float) -> "list[tuple[float, float]]":
        """(t depuis charge, %) des seuls événements brûleur, triés par temps.

        Doctrine Artisan : specialevents[k] est un INDEX dans timex (pas des
        secondes) ; specialeventsvalue[k] est la valeur interne (8.0 → 70 %),
        décodée par events_internal_to_external_value ; le brûleur est l'etype 3.

        Centralisé : plusieurs lectures de la main de l'opérateur en dépendent
        (valeur tenue par phase, descente avant le DRY END). Les faire chacune
        de leur côté, c'est se garantir qu'elles divergeront.
        """
        evt_idx  = data.get("specialevents", []) or []
        evt_type = data.get("specialeventstype", []) or []
        evt_val  = data.get("specialeventsvalue", []) or []
        tx = data.get("timex", []) or []
        out: list[tuple[float, float]] = []
        for k in range(min(len(evt_idx), len(evt_type), len(evt_val))):
            if int(evt_type[k]) != self._BURNER_ETYPE:
                continue
            i = int(evt_idx[k])
            if not (0 <= i < len(tx)):
                continue
            pct = float(events_internal_to_external_value(float(evt_val[k])))
            if not (0.0 <= pct <= 100.0):   # rejette l'encodage brut / aberrations
                continue
            out.append((float(tx[i]) - charge_ts, pct))
        out.sort(key=lambda e: e[0])
        return out

    ## Bruit de charge : les premières secondes portent la montée du réglage
    ## initial (65→90→75 en 2 s), qui n'est pas une conduite de roast.
    _DESCENT_IGNORE_SEC: Final[float] = 15.0
    ## Une baisse plus petite n'est pas un geste : c'est la résolution du curseur.
    _DESCENT_MIN_PCT: Final[float] = 1.0

    def _extract_pre_de_descent(self, phase_times: dict
                                ) -> "tuple[float, float] | None":
        """Premier geste de descente EFFECTIVE du brûleur avant le DRY END.

        Renvoie `(lead_sec, step_pct)` : combien de secondes avant le DRY END
        l'opérateur a commencé à descendre, et la taille TYPIQUE de ses crans
        sur cette descente. None quand il n'a rien touché avant le DRY END —
        c'est le cas normal, pas une anomalie : réglage de charge juste, rien
        à corriger.

        Pourquoi ce point-là et pas la valeur tenue au DRY END : cette dernière
        est l'état d'ARRIVÉE de tout ce qui s'est passé pendant le séchage, elle
        confond une conduite normale et une correction de RoR. Le premier geste
        descendant est ce qui distingue les deux.

        Pourquoi la taille du cran : la limite d'observabilité (5 %) est un
        PLAFOND, pas une granularité. Mesurée sur la main de l'opérateur elle
        vaut 1 à 3 % — rejouer sa descente par crans de 5 % lui proposerait des
        gestes deux à cinq fois plus gros que les siens.
        """
        try:
            data = self.lastprofiledata
            ti = data.get("timeindex", []) or []
            tx = data.get("timex", []) or []
            t_dry = phase_times.get("dry_end")
            if not (ti and tx) or ti[RoastingPhase.CHARGE] < 0 or not t_dry or t_dry <= 0:
                return None
            burner = self._burner_events(data, float(tx[ti[RoastingPhase.CHARGE]]))
            # Le réglage de CHARGE est la référence de la descente : il est posé
            # dans le bruit des premières secondes (65→90→75 en 2 s), qu'on
            # écarte — mais sa VALEUR doit rester, sinon le premier vrai geste
            # passe pour la référence et on perd un cran.
            baseline = next((v for t, v in reversed(burner)
                             if t < self._DESCENT_IGNORE_SEC), None)
            window = [(t, v) for t, v in burner
                      if self._DESCENT_IGNORE_SEC <= t <= float(t_dry)]
            if baseline is not None:
                window.insert(0, (self._DESCENT_IGNORE_SEC, baseline))
            if len(window) < 2:
                return None
            drops = [(t, window[i - 1][1] - v)
                     for i, (t, v) in enumerate(window[1:], start=1)
                     if window[i - 1][1] - v >= self._DESCENT_MIN_PCT]
            if not drops:
                return None
            lead_sec = float(t_dry) - drops[0][0]
            step_pct = float(np.median([d for _, d in drops]))
            return lead_sec, step_pct
        except (KeyError, IndexError, TypeError, ValueError) as e:
            _logd.debug(f"_extract_pre_de_descent failed: {e}")
            return None

    def _extract_phase_heater(self, phase_times: dict) -> "tuple[float | None, float | None, float | None, float | None, float | None]":
        """Représentation du heater réellement tenu par phase (dry, maillard,
        dev, fc, de) sur le log courant (self.lastprofiledata) — la valeur du
        brûleur en vigueur au MILIEU de chaque phase, plus la valeur en vigueur
        À L'INSTANT du FC (palier pre-FC appris, item C Bench-Integration) et
        À L'INSTANT du DRY END.

        La valeur au DE sert au geste PRÉVENTIF anti-flick : quand l'opérateur
        baisse systématiquement le feu avant la fin du séchage pour éviter un
        flick au DE, c'est SA valeur qu'on rejoue — pas un pourcentage deviné.
        Comparée à la médiane de séchage, elle dit s'il y a eu baisse et de
        combien.

        Doctrine Artisan : specialevents[k] est un INDEX dans timex (pas des
        secondes) ; specialeventsvalue[k] est la valeur interne (8.0 → 70 %),
        décodée par events_internal_to_external_value ; le brûleur est
        l'etype 3. La valeur au milieu = dernier événement burner posé à ou
        avant le milieu de phase (report du réglage de charge inclus). None par
        phase si aucun événement burner exploitable ou phase absente.
        """
        try:
            data = self.lastprofiledata
            evt_idx  = data.get("specialevents", []) or []
            evt_type = data.get("specialeventstype", []) or []
            evt_val  = data.get("specialeventsvalue", []) or []
            ti = data.get("timeindex", []) or []
            tx = data.get("timex", []) or []
            if not (evt_idx and ti and tx) or ti[RoastingPhase.CHARGE] < 0:
                return None, None, None, None, None
            charge_ts = float(tx[ti[RoastingPhase.CHARGE]])
            burner = self._burner_events(data, charge_ts)
            if not burner:
                return None, None, None, None, None

            def _held_at(t_mid: float) -> "float | None":
                # dernier réglage burner à ou avant t_mid (report de charge)
                held = None
                for t_sc, pct in burner:
                    if t_sc <= t_mid + 1e-6:
                        held = pct
                    else:
                        break
                return held

            t_dry  = phase_times.get("dry_end")
            t_fc   = phase_times.get("fc_start")
            t_drop = phase_times.get("drop")
            dry = _held_at(t_dry / 2.0) if (t_dry and t_dry > 0) else None
            mai = (_held_at((t_dry + t_fc) / 2.0)
                   if (t_dry and t_fc and t_fc > t_dry) else None)
            dev = (_held_at((t_fc + t_drop) / 2.0)
                   if (t_fc and t_drop and t_drop > t_fc) else None)
            # ## TILAU ## item C : valeur tenue À L'INSTANT du FC — le palier
            # pre-FC appris (décision Tilau : FC appris, backup calcul du plan).
            fc_h = _held_at(t_fc) if (t_fc and t_fc > 0) else None
            # Valeur tenue À L'INSTANT du DRY END — voir le docstring : c'est
            # l'observable du geste préventif anti-flick.
            de_h = _held_at(t_dry) if (t_dry and t_dry > 0) else None
            return dry, mai, dev, fc_h, de_h
        except (KeyError, IndexError, TypeError, ValueError) as e:
            _logd.debug(f"_extract_phase_heater failed: {e}")
            return None, None, None, None, None

    # etypes des leviers dont on apprend la trajectoire de développement
    _DEV_TRAJ_ETYPES: "tuple[int, ...]" = (0, 2, 3)   # air, extraction, burner
    _DEV_TRAJ_FRACS:  "tuple[float, ...]" = (0.25, 0.5, 0.75, 1.0)

    def _extract_dev_trajectory(self, phase_times: dict
                                ) -> "dict[int, dict[float, float]] | None":
        """## TILAU ## Trajectoire CONTINUE tenue en développement (FC→DROP) sur
        le log courant, pour air (etype 0), extraction (2) et burner (3).

        Généralise `_extract_phase_heater` : au lieu d'un seul point mi-phase,
        échantillonne la valeur en vigueur (dernier événement du levier ≤ t) à
        plusieurs fractions de la phase DEV. Sert à APPRENDRE la forme réelle
        (l'opérateur baisse le feu et monte l'airflow en continu) plutôt que de
        s'arrêter à un réglage de jalon. Les % de slider sont sans unité : aucune
        conversion °C/°F. None si DEV absente ou aucun événement exploitable."""
        try:
            data = self.lastprofiledata
            evt_idx  = data.get("specialevents", []) or []
            evt_type = data.get("specialeventstype", []) or []
            evt_val  = data.get("specialeventsvalue", []) or []
            ti = data.get("timeindex", []) or []
            tx = data.get("timex", []) or []
            if not (evt_idx and ti and tx) or ti[RoastingPhase.CHARGE] < 0:
                return None
            t_fc   = phase_times.get("fc_start")
            t_drop = phase_times.get("drop")
            if not (t_fc and t_drop and t_drop > t_fc):
                return None
            charge_ts = float(tx[ti[RoastingPhase.CHARGE]])
            n = min(len(evt_idx), len(evt_type), len(evt_val))
            out: "dict[int, dict[float, float]]" = {}
            for etype in self._DEV_TRAJ_ETYPES:
                ev: list[tuple[float, float]] = []
                for k in range(n):
                    if int(evt_type[k]) != etype:
                        continue
                    i = int(evt_idx[k])
                    if not (0 <= i < len(tx)):
                        continue
                    pct = float(events_internal_to_external_value(float(evt_val[k])))
                    if not (0.0 <= pct <= 100.0):
                        continue
                    ev.append((float(tx[i]) - charge_ts, pct))
                if not ev:
                    continue
                ev.sort(key=lambda e: e[0])

                def _held_at(t_abs: float, _ev=ev) -> "float | None":
                    held = None
                    for t_sc, pct in _ev:
                        if t_sc <= t_abs + 1e-6:
                            held = pct
                        else:
                            break
                    return held

                per_frac: dict[float, float] = {}
                for f in self._DEV_TRAJ_FRACS:
                    v = _held_at(t_fc + (t_drop - t_fc) * f)
                    if v is not None:
                        per_frac[f] = v
                if per_frac:
                    out[etype] = per_frac
            return out or None
        except (KeyError, IndexError, TypeError, ValueError) as e:
            _logd.debug(f"_extract_dev_trajectory failed: {e}")
            return None

    def _which_phase(self, current_time: float, phase_times: dict) -> int:
        """
        Détermine la phase de torréfaction pour un timestamp donné (secondes depuis charge).
        
        :param current_time: temps en secondes depuis charge
        :param phase_times: dict avec les clés 'dry_end', 'fc_start', 'drop' (secondes depuis charge)
        :return: index de phase (1=DRY, 2=MAILLARD, 3=DEVELOPMENT, 0=hors scope)
        """
        dry_end  = phase_times.get("dry_end")
        fc_start = phase_times.get("fc_start")
        drop     = phase_times.get("drop")

        if drop is None:
            return 0  # données insuffisantes

        if dry_end is not None and current_time <= dry_end:
            return 1  # DRY
        if fc_start is not None and current_time <= fc_start:
            return 2  # MAILLARD
        # FC non marqué : on ne peut PAS distinguer Maillard de Development sur ce log.
        # Étiqueter tout l'après-séchage en DEVELOPMENT polluait les statistiques de phase
        # (crashes/flicks Maillard comptés comme dev). On renvoie 0 (hors scope) pour la
        # zone ambiguë afin que _average_event_group ignore ces événements non fiables.
        if fc_start is None:
            return 0
        if current_time <= drop:
            return 3  # DEVELOPMENT
        return 0  # hors scope (post-drop)

    def _prepare_historical_graph_data(self, relevant_logs_data: list):
        """
        Prépare une 'Master Curve' (moyenne) et une enveloppe (min/max) 
        à partir des logs historiques.
        """
        if not relevant_logs_data:
            return None

        # 1. Créer une grille de temps commune (ex: 0 à 15 min par pas de 1s)
        max_duration = max([max(d['timex']) for d in relevant_logs_data])
        common_time = np.arange(0, max_duration, 1) # Grille de 1 seconde
        
        all_ror = []
        all_bt = []
        
        for data in relevant_logs_data:
            # Interpolation pour aligner les données sur la grille commune
            ror_interp = np.interp(common_time, data['timex'], data['delta_bt'], left=0, right=np.nan)
            bt_interp = np.interp(common_time, data['timex'], data['bt'], left=np.nan, right=np.nan)
            all_ror.append(ror_interp)
            all_bt.append(bt_interp)

        # 2. Calculer les statistiques
        np_all_ror = np.array(all_ror)
        np_all_bt = np.array(all_bt)
        # RoR clip is °C-doctrine — scale on °F installs (series is display-unit)
        _s = 1.8 if self.mode == "F" else 1.0
        np_all_ror = np.clip(np_all_ror, -2.0 * _s, 35.0 * _s)
        ror_min = np.nanmin(np_all_ror, axis=0)
        ror_max = np.nanmax(np_all_ror, axis=0)
        if len(relevant_logs_data) == 1:
            ror_min = ror_min * 0.95
            ror_max = ror_max * 1.05
        bt_min = np.nanmin(np_all_bt, axis=0)
        bt_max = np.nanmax(np_all_bt, axis=0)
        if len(relevant_logs_data) == 1:
            bt_min = bt_min * 0.99
            bt_max = bt_max * 1.01
        master_data = {
            "time_min": (common_time / 60.0).tolist(), # Temps en minutes
            "ror_mean": np.nanmean(np_all_ror, axis=0).tolist(),
            "ror_min": ror_min.tolist(),
            "ror_max": ror_max.tolist(),
            "bt_mean": np.nanmean(np_all_bt, axis=0).tolist(),
            "bt_min":  bt_min.tolist(),    # ← add
            "bt_max":  bt_max.tolist(),    # ← add
            # Phases moyennes (basées sur le premier log ou la moyenne des phases)
            "phase_times": relevant_logs_data[0].get("phase_times", {}) 
        }
        
        return master_data

    def _get_history_cached(self, bean: GreenBean, target_agtron: AgtronScale,
                            charge_weight_g: float):
        """
        Memoised front-end to _analyze_historical_roasts.

        Serves shallow copies (with fresh 'notes'/'actions' lists) so that
        per-plan mutations — e.g. the timing-calibration notes appended by
        generate_roast_plan — never leak back into the cache and duplicate
        on the next regeneration.
        """
        key = (getattr(bean, "uuid", "") or bean.name,
               target_agtron.name, round(charge_weight_g))
        if key not in self._history_cache:
            self._history_cache[key] = self._analyze_historical_roasts(
                bean, target_agtron, charge_weight_g)
        else:
            _logd.debug(f"RoastPlan: history served from cache for {key}")
        cached = self._history_cache[key]
        if cached is None:
            return None
        out = dict(cached)
        out["notes"]   = list(cached.get("notes")   or [])
        out["actions"] = list(cached.get("actions") or [])
        return out

    def _analyze_historical_roasts(self, bean: GreenBean, target_agtron:AgtronScale,
                                   charge_weight_g: float = 0.0):
        """
        Refactored: Analyzes logs filtered by bean identity (uuid first, fuzzy
        name as fallback) and Agtron target.
        Data quality filters applied before building the master curve:
          - Exclude alogs with Ambient Temp=0 or Humidity=0 (sensor not connected)
          - Exclude alogs with Charge BT < 150°C (cold charge / misfired roast)
          - Batch weight similarity: exclude alogs whose green weight differs
            from the planned charge by more than ±25% (a 250 g and a 450 g
            batch of the same bean have incomparable RoR curves)
          - Machine fingerprint: radiant (ET>BT at TP, delta~+26°C) vs drum (ET<BT)
            — only alogs matching the current roaster type are included
        """
        feedback_notes = []
        adjustments = []

        # Determine expected machine fingerprint from RoasterContext
        # Radiant: TP_ET > TP_BT (positive delta)
        # Drum:    TP_ET < TP_BT (negative delta)
        _is_radiant = (self._roaster_ctx.is_radiant_electric
                       if self._roaster_ctx is not None else None)
        
        historical_logs = self._list_alogs()
        # 1. Bean identity — uuid is AUTHORITATIVE when the bean has one:
        # zero uuid hits then means "no history for THIS bean" (fresh bean →
        # grid plan). Falling back on the fuzzy name in that case silently
        # borrowed roasts of other coffees sharing a token (variety names like
        # "Caturra" match other lots' filenames at 100%) and produced false
        # "learned (n=N)" plans for never-roasted beans. The fuzzy filename
        # match remains ONLY for beans without a BeanCave uuid (legacy
        # imports); legacy logs of a uuid-bean can be re-linked via Repair
        # ALogs ("Complete from bean" writes the uuid into the beans field).
        _bean_uuid = getattr(bean, "uuid", "") or ""
        potential_logs = self._find_logs_by_uuid(_bean_uuid, historical_logs)
        if potential_logs:
            _logd.debug(f"_analyze_historical_roasts: {len(potential_logs)} log(s) matched by uuid")
        elif _bean_uuid:
            _logd.info(f"_analyze_historical_roasts: no log carries the uuid of '{bean.name}' "
                       "— fresh bean, grid plan (name fallback disabled for uuid beans)")
            return None
        else:
            potential_logs = self._find_relevant_logs(bean.name, historical_logs)
            if potential_logs:
                _logd.debug(f"_analyze_historical_roasts: {len(potential_logs)} log(s) "
                            "matched by fuzzy name (bean has no uuid)")
        
        relevant_logs_data = []
        fc_samples_c: list[float] = []   # measured FCs_BT of quality-filtered logs (°C)
        charge_samples_c: list[float] = []   # charge BT of each FC sample (°C) — for FC regression
        dry_time_samples_min: list[float] = []   # realized drying duration (min)
        fc_time_samples_min:  list[float] = []   # realized time-to-FC since charge (min)
        drop_color_samples_c: list[float] = []   # drop BT corrected to target colour (°C)
        peak_ror_samples: list[float] = []       ## TILAU ## RoR peak (~2:41, °C/min) — bean property, drives the setup loop
        # Heater réellement tenu par phase — COULEUR-ASSORTIE (collecté sous le
        # gate Agtron) : le heater de dev dépend fortement de la cible couleur.
        heater_dry_samples:  list[float] = []
        heater_mai_samples:  list[float] = []
        heater_dev_samples:  list[float] = []
        heater_fc_samples:   list[float] = []   ## TILAU ## item C : feu tenu AU FC
        # Feu tenu AU DRY END : point d'arrivée du séchage.
        heater_de_samples:   list[float] = []
        # Premier geste de descente EFFECTIVE avant le DRY END : son avance sur
        # le jalon, et la taille des crans de l'opérateur sur cette descente.
        pre_de_lead_samples: list[float] = []
        pre_de_step_samples: list[float] = []
        # RoR au drop réellement obtenu — COULEUR-ASSORTI (le RoR de fin de     ## TILAU ##
        # courbe dépend de la cible couleur/DTR). Spec Bench-Integration item A. ## TILAU ##
        drop_ror_samples_c:  list[float] = []
        # Trajectoire DEV apprise (air/ext/burner × fractions de phase) —        ## TILAU ##
        # samples[etype][frac] = liste de % tenus ; médiane par (levier, frac).  ## TILAU ##
        dev_traj_samples: "dict[int, dict[float, list[float]]]" = {
            et: {f: [] for f in self._DEV_TRAJ_FRACS} for et in self._DEV_TRAJ_ETYPES}
        for log in potential_logs:
            delta_bt, timex, bt, tp_index, phase_times = self._get_delta_bt(log)

            if not delta_bt:
                continue

            # ── Learning exclusions ─────────────────────────────────────────
            # Simulated roasts (tilau_simulated, stamped at save) are not
            # physical data; tilau_exclude_learning is the operator's explicit
            # veto from the EOR page. Both were already honoured by the
            # adaptive PID — the plan learning must skip them too.
            if self.lastprofiledata.get("tilau_simulated", False):
                _logd.debug(f"_analyze_historical_roasts: skipping {log.name} — simulated roast")
                continue
            if self.lastprofiledata.get("tilau_exclude_learning", False):
                _logd.debug(f"_analyze_historical_roasts: skipping {log.name} — excluded from learning by operator")
                continue

            # ── Data quality filter 1: ambient conditions ──────────────────
            _ambient_temp = self.lastprofiledata.get("computed", {}).get("ambient_temperature", 0.0) or 0.0
            _ambient_hum  = self.lastprofiledata.get("computed", {}).get("ambient_humidity",    0.0) or 0.0
            if _ambient_temp == 0.0 or _ambient_hum == 0.0:
                _logd.debug(f"_analyze_historical_roasts: skipping {log.name} — missing ambient data")
                continue

            # ── Data quality filter 2: charge BT plausibility ──────────────
            # computed values live in the LOG's own unit — normalise to °C
            # before applying the °C-doctrine thresholds.
            _log_is_f = str(self.lastprofiledata.get("mode", "C")) == "F"
            _charge_bt = self.lastprofiledata.get("computed", {}).get("CHARGE_BT", 0.0) or 0.0
            _charge_bt_c = fromFtoCstrict(_charge_bt) if (_log_is_f and _charge_bt > 0.0) else _charge_bt
            if _charge_bt_c > 0.0 and _charge_bt_c < 150.0:
                _logd.debug(f"_analyze_historical_roasts: skipping {log.name} — charge BT too low ({_charge_bt_c:.1f}°C)")
                continue

            # ── Data quality filter 3: batch weight similarity ──────────────
            # A log roasted at a very different batch size has an incomparable
            # RoR curve; mixing it into the master curve corrupts the envelope.
            _WEIGHT_TOL = 0.25   # ±25% of the planned charge
            if charge_weight_g > 0.0:
                _w = self.lastprofiledata.get("weight")
                _w_green = 0.0
                if _w:
                    try:
                        _units = ["g", "Kg", "lb", "oz"]
                        _w_green = convertWeight(float(_w[0]), _units.index(str(_w[2])), 0)
                    except (ValueError, TypeError, IndexError):
                        _w_green = 0.0
                if _w_green <= 0.0:
                    _logd.debug(f"_analyze_historical_roasts: skipping {log.name} — missing green weight")
                    continue
                if abs(_w_green - charge_weight_g) / charge_weight_g > _WEIGHT_TOL:
                    _logd.debug(
                        f"_analyze_historical_roasts: skipping {log.name} — batch weight "
                        f"{_w_green:.0f}g vs plan {charge_weight_g:.0f}g (>±{_WEIGHT_TOL:.0%})")
                    continue

            # ── Data quality filter 4: machine fingerprint via ET/BT at TP ─
            # Only apply when RoasterContext is available and both TP temps exist.
            if _is_radiant is not None:
                _tp_bt = self.lastprofiledata.get("computed", {}).get("TP_BT", 0.0) or 0.0
                _tp_et = self.lastprofiledata.get("computed", {}).get("TP_ET", 0.0) or 0.0
                if _tp_bt > 0.0 and _tp_et > 0.0:
                    _tp_delta = _tp_et - _tp_bt  # positive = ET>BT = radiant
                    if _log_is_f:
                        _tp_delta /= 1.8         # delta °F -> °C for the ±5 °C thresholds
                    _log_is_radiant = _tp_delta > 5.0   # threshold: >+5°C = radiant
                    _log_is_drum    = _tp_delta < -5.0  # threshold: <-5°C = drum
                    if _is_radiant and _log_is_drum:
                        _logd.debug(f"_analyze_historical_roasts: skipping {log.name} — drum fingerprint on radiant roaster (TP delta={_tp_delta:.1f}°C)")
                        continue
                    if not _is_radiant and _log_is_radiant:
                        _logd.debug(f"_analyze_historical_roasts: skipping {log.name} — radiant fingerprint on drum roaster (TP delta={_tp_delta:.1f}°C)")
                        continue

            # ── FC learning sample — collected BEFORE the Agtron gate: the FC
            # temperature is a physical property of the bean on this rig,
            # independent of the target roast level, so every quality-filtered
            # log contributes regardless of its final colour.
            # Also collect charge BT for FC regression (charge influences FC temp).
            _fc_log = self.lastprofiledata.get("computed", {}).get("FCs_BT", 0.0) or 0.0
            if _fc_log > 0.0:
                _log_mode = str(self.lastprofiledata.get("mode", "C"))
                fc_c = fromFtoCstrict(float(_fc_log)) if _log_mode == "F" else float(_fc_log)
                fc_samples_c.append(fc_c)
                charge_samples_c.append(_charge_bt_c)  # parallel list for regression

            # ── Drop-colour learning sample — also PRE-Agtron-gate: every log
            # with a MEASURED colour (result form / colorimeter) teaches where
            # this bean lands. The sample is the log's drop BT corrected to the
            # CURRENT target colour via the fleet-measured slope (−0.323 °C per
            # Agtron point, 144 roasts) — no need to know the past target.
            # Capped at ±15 pts to stay interpolative (no long extrapolation).
            _drop_log  = self.lastprofiledata.get("computed", {}).get("DROP_BT", 0.0) or 0.0
            _color_log = self._average_color_in_agtron(
                max(self.lastprofiledata.get("whole_color", 0) or 0,
                    self.lastprofiledata.get("ground_color", 0) or 0),
                self.lastprofiledata.get("color_system", ""))
            if _drop_log > 0.0 and _color_log > 0.0:
                _target_mid = (target_agtron.agtron_range.min_value
                               + target_agtron.agtron_range.max_value) / 2.0
                _color_gap = _target_mid - _color_log
                if abs(_color_gap) <= 15.0:
                    _log_mode = str(self.lastprofiledata.get("mode", "C"))
                    _drop_c = (fromFtoCstrict(float(_drop_log)) if _log_mode == "F"
                               else float(_drop_log))
                    drop_color_samples_c.append(_drop_c - 0.323 * _color_gap)

            # ── Timing calibration samples — same pre-Agtron rationale: the
            # time to dry-end / to FC barely depends on the target colour.
            # Paired samples only (both events marked, in the right order).
            _dry_t = self.lastprofiledata.get("computed", {}).get("DRY_time", 0.0) or 0.0
            _fcs_t = self.lastprofiledata.get("computed", {}).get("FCs_time", 0.0) or 0.0
            if _dry_t > 0.0 and _fcs_t > _dry_t:
                dry_time_samples_min.append(float(_dry_t) / 60.0)
                fc_time_samples_min.append(float(_fcs_t) / 60.0)

            # ── Peak RoR learning sample — PRE-Agtron-gate (bean property, the   ## TILAU ##
            # anchor of the descent, ~2:41). Drives the cross-roast setup loop    ## TILAU ##
            # (charge-temp correction). delta_bt is in the display unit → °C/min. ## TILAU ##
            if delta_bt and timex:
                _pk = max((delta_bt[i] for i in range(min(len(delta_bt), len(timex)))
                           if 50.0 <= timex[i] <= 240.0), default=None)
                if _pk is not None:
                    _pk_c = _pk / 1.8 if self.mode == "F" else _pk
                    if 8.0 <= _pk_c <= 30.0:   # glitch guard (impossible RoR = sensor jump)
                        peak_ror_samples.append(_pk_c)

            # 2. Filter by Agtron Category
            color_system = self.lastprofiledata.get("color_system","")
            # use the lighter roast from the two figures (max value)
            agtron_plan = self._average_color_in_agtron(max(self.lastprofiledata.get("whole_color",0),self.lastprofiledata.get("ground_color",0)), color_system)
            if (agtron_plan >= target_agtron.agtron_range.min_value and agtron_plan <= target_agtron.agtron_range.max_value):
                relevant_logs_data.append({
                    "delta_bt": delta_bt,
                    "timex": timex,
                    "bt": bt,
                    "tp_index":    tp_index,    # Bug corrigé : tp_index propre à chaque log
                    "phase_times": phase_times, # Bug corrigé : phase_times propre à chaque log
                })
                # Heater tenu par phase (couleur-assortie) — un échantillon par
                # phase et par roast, valeur en vigueur au milieu de la phase,
                # plus la valeur au FC (palier pre-FC appris, item C).
                _h_dry, _h_mai, _h_dev, _h_fc, _h_de = self._extract_phase_heater(phase_times)
                if _h_dry is not None:
                    heater_dry_samples.append(_h_dry)
                if _h_mai is not None:
                    heater_mai_samples.append(_h_mai)
                if _h_dev is not None:
                    heater_dev_samples.append(_h_dev)
                if _h_fc is not None:
                    heater_fc_samples.append(_h_fc)
                if _h_de is not None:
                    heater_de_samples.append(_h_de)
                # Gardes de plausibilité à la COLLECTE, comme pour le RoR de pic
                # et le RoR au drop : un échantillon aberrant doit sortir avant
                # la médiane, pas être filtré après coup côté plan.
                # Avance > 5 min = geste du tout début, pas une entrée de DRY END.
                # Cran > 5 % = au-delà de la limite d'observabilité : le plan ne
                # le proposerait jamais, donc l'apprendre ne sert à rien.
                _descent = self._extract_pre_de_descent(phase_times)
                if (_descent is not None
                        and 15.0 <= _descent[0] <= 300.0
                        and self._DESCENT_MIN_PCT <= _descent[1] <= self._OBSERVABLE_PCT):
                    pre_de_lead_samples.append(_descent[0])
                    pre_de_step_samples.append(_descent[1])
                # Trajectoire DEV continue (même cohorte couleur-assortie)      ## TILAU ##
                _traj = self._extract_dev_trajectory(phase_times)
                if _traj:
                    for _et, _pf in _traj.items():
                        for _f, _v in _pf.items():
                            dev_traj_samples[_et][_f].append(_v)
                # RoR au drop (même cohorte) : médiane du delta_bt sur les      ## TILAU ##
                # 15 s précédant le DROP (robuste au retrait de sonde / spike   ## TILAU ##
                # de fin). delta_bt est en unité d'affichage → °C/min.          ## TILAU ##
                _drop_t = self.lastprofiledata.get("computed", {}).get("DROP_time", 0.0) or 0.0
                if _drop_t > 0.0 and delta_bt and timex:
                    _win = [delta_bt[i] for i in range(min(len(delta_bt), len(timex)))
                            if _drop_t - 15.0 <= timex[i] <= _drop_t
                            and delta_bt[i] is not None]
                    if _win:
                        _dr = float(np.median(_win))
                        _dr_c = _dr / 1.8 if self.mode == "F" else _dr
                        if 0.5 <= _dr_c <= 12.0:   # glitch guard (sensor jump)
                            drop_ror_samples_c.append(_dr_c)

        # ── FC linear regression by charge ────────────────────────────────
        # FC is correlated with initial charge temperature (higher charge → higher FC).
        # Learn FC = a × Charge + b coefficients; will be applied in generate_roast_plan.
        fc_regression_slope: float | None = None
        fc_regression_offset: float | None = None

        if fc_samples_c and len(fc_samples_c) >= 3 and charge_samples_c and len(charge_samples_c) == len(fc_samples_c):
            charges = np.array(charge_samples_c, dtype=float)
            fcs = np.array(fc_samples_c, dtype=float)
            charge_mean = float(np.mean(charges))
            fc_mean = float(np.mean(fcs))
            cov = float(np.sum((charges - charge_mean) * (fcs - fc_mean))) / len(charges)
            var = float(np.sum((charges - charge_mean) ** 2)) / len(charges)

            if var > 0.01:  # avoid division by zero
                a = cov / var
                b = fc_mean - a * charge_mean
                fc_regression_slope = round(a, 4)
                fc_regression_offset = round(b, 2)
                _logd.debug(f"FC regression learned: FC = {a:.4f} × Charge + {b:.2f}°C "
                           f"(n={len(fc_samples_c)}, samples: {list(zip(charge_samples_c, fc_samples_c))})")

        # Medians: robust against one mis-marked event in the cohort.
        fc_bt_learned_c: float | None = (round(float(np.median(fc_samples_c)), 1)
                                         if fc_samples_c else None)
        timing_dry_learned: float | None = (round(float(np.median(dry_time_samples_min)), 2)
                                            if dry_time_samples_min else None)
        timing_fc_learned: float | None = (round(float(np.median(fc_time_samples_min)), 2)
                                           if fc_time_samples_min else None)
        drop_bt_learned_c: float | None = (round(float(np.median(drop_color_samples_c)), 1)
                                           if drop_color_samples_c else None)
        # Dispersions robustes (MAD) — mesurent la CONFIANCE de l'historique :
        # un grain régulier resserre les seuils du coach, un historique bruité
        # (jalons mal marqués, lots hétérogènes) les relâche (bloc tolérances).
        def _mad(samples: list[float]) -> "float | None":
            if len(samples) < 2:
                return None
            med = float(np.median(samples))
            return round(float(np.median([abs(s - med) for s in samples])), 2)
        fc_bt_mad_c   = _mad(fc_samples_c)
        drop_bt_mad_c = _mad(drop_color_samples_c)
        # Heater appris par phase : médiane du % tenu (couleur-assortie). Le
        # nombre d'échantillons peut différer par phase (un dev non marqué ne
        # fournit pas de sample dev) → compte par phase, min pour l'adoption.
        def _med(samples: list[float]) -> "float | None":
            return round(float(np.median(samples)), 1) if samples else None
        heater_dry_learned = _med(heater_dry_samples)
        heater_mai_learned = _med(heater_mai_samples)
        heater_dev_learned = _med(heater_dev_samples)
        heater_samples = min(len(heater_dry_samples), len(heater_mai_samples),
                             len(heater_dev_samples))
        heater_fc_learned = _med(heater_fc_samples)   ## TILAU ## item C
        heater_de_learned = _med(heater_de_samples)
        pre_de_lead_learned = _med(pre_de_lead_samples)
        pre_de_step_learned = _med(pre_de_step_samples)
        peak_ror_learned = _med(peak_ror_samples)   ## TILAU ## setup loop : pic médian du grain (°C/min)
        peak_ror_n = len(peak_ror_samples)           ## TILAU ##
        # Trajectoire DEV apprise : médiane par (levier, fraction) + n min sur   ## TILAU ##
        # les fractions d'un levier (un levier jamais bougé → pas de trajectoire).
        dev_trajectory_learned: "dict[int, dict[float, float]]" = {}
        dev_traj_n = 0
        for _et, _fracs in dev_traj_samples.items():
            _per: dict[float, float] = {}
            _counts: list[int] = []
            for _f, _vals in _fracs.items():
                if _vals:
                    _per[_f] = round(float(np.median(_vals)), 1)
                    _counts.append(len(_vals))
            if _per:
                dev_trajectory_learned[_et] = _per
                dev_traj_n = max(dev_traj_n, min(_counts))

        if not relevant_logs_data:
            if fc_bt_learned_c is None and timing_dry_learned is None and drop_bt_learned_c is None:
                return None
            # No log matches the target colour (no master curve possible), but
            # FC temperature / phase timings / colour response were still
            # learnable from other roast levels of the same bean.
            return {"notes": [], "actions": [], "graph": None,
                    "crashes": [], "flicks": [],
                    "fc_bt_learned_c": fc_bt_learned_c,
                    "fc_bt_samples": len(fc_samples_c),
                    "fc_regression_slope": fc_regression_slope,   ## TILAU ## FC = a × Charge + b
                    "fc_regression_offset": fc_regression_offset, ## TILAU ##
                    "timing_dry_min_learned": timing_dry_learned,
                    "timing_fc_min_learned": timing_fc_learned,
                    "timing_samples": len(dry_time_samples_min),
                    "drop_bt_learned_c": drop_bt_learned_c,
                    "drop_bt_samples": len(drop_color_samples_c),
                    "fc_bt_mad_c": fc_bt_mad_c,
                    "drop_bt_mad_c": drop_bt_mad_c,
                    "dev_trajectory_learned": dev_trajectory_learned,
                    "dev_traj_samples": dev_traj_n,
                    "peak_ror_learned": peak_ror_learned,   ## TILAU ## setup loop
                    "peak_ror_n": peak_ror_n}               ## TILAU ##

        crashes_raw = []
        flicks_raw = []

        for data in relevant_logs_data: # arrays are from charge to drop only
            tx          = data["timex"]
            tp_idx      = data["tp_index"]    # plus de fuite de scope
            phase_times = data["phase_times"] # plus de fuite de scope
            drop_time   = phase_times["drop"]
            f, c = self._find_flicks_crashes(
                data["delta_bt"], tx, phase_times, tp_idx,
                # delta series is in the display unit — the °C-doctrine
                # prominence (1 °C/min) scales ×1.8 on °F installs.
                prominence=1.0 * (1.8 if self.mode == "F" else 1.0),
                debounce_sec=20.0 * (1.5 - getattr(self, '_thermal_response_speed_cache', 0.70)),
            )

            # 3. Filter out Post-Drop artifacts immediately
            flicks_raw.append([item for item in f if item["time"] <= drop_time])
            crashes_raw.append([item for item in c if item["time"] <= drop_time])

        # 4. Merge using improved grouping
        crashes_detected = self._merge_events_by_phase(crashes_raw)
        flicks_detected = self._merge_events_by_phase(flicks_raw)
        # compute charge time after information is being loaded bu _get_delta_bt
        #time_index = self.lastprofiledata.get("timeindex",[])
        #charge_in_sec = time_index[0] if len(time_index) > 0 and time_index[0] > -1 else 0

        for crash in crashes_detected:
            phase = crash.get("phase", QApplication.translate("tilauscope_roast_plan","OUT OF SCOPE"))
            occurrences = crash.get("occurrence_count", 1)
            time_str = self.format_time((crash["time"])/60.0)
            
            msg = QApplication.translate("tilauscope_roast_plan","CRASH")+f" ({occurrences}x) "+QApplication.translate("tilauscope_roast_plan","at")+f" {time_str} "+QApplication.translate("tilauscope_roast_plan","during")+f" {phase}. "+QApplication.translate("tilauscope_roast_plan","Severity")+f": {crash['severity']}"
            feedback_notes.append(msg)
            
            # Specific advice based on phase
            if "Maillard" in phase or "Development" in phase:
                adjustments.append(QApplication.translate("tilauscope_roast_plan","Action: Boost heater")+" 5% "+QApplication.translate("tilauscope_roast_plan","at")+f" {self.format_time((crash['time']-30)/60.0)} "+QApplication.translate("tilauscope_roast_plan","to prevent crash."))
            else:
                adjustments.append(QApplication.translate("tilauscope_roast_plan","Action: Monitor momentum; consider reducing airflow."))

        for flick in flicks_detected:
            phase = flick.get("phase", QApplication.translate("tilauscope_roast_plan","OUT OF SCOPE"))
            occurrences = flick.get("occurrence_count", 1)
            time_str = self.format_time(flick["time"]/60.0)
            
            msg = QApplication.translate("tilauscope_roast_plan","FLICK")+f" ({occurrences}x) "+QApplication.translate("tilauscope_roast_plan","at")+f" {time_str} "+QApplication.translate("tilauscope_roast_plan","during")+f" {phase}. "+QApplication.translate("tilauscope_roast_plan","Severity")+f": {flick['severity']}"
            feedback_notes.append(msg)
            
            if "Development" in phase:
                adjustments.append(QApplication.translate("tilauscope_roast_plan","Action: Reduce burner 10% 45s before")+f" {time_str} "+QApplication.translate("tilauscope_roast_plan","to smooth RoR."))
            else:
                adjustments.append(QApplication.translate("tilauscope_roast_plan","Action: Increase extraction/airflow to shed thermal energy."))
    
        master_graph_data = self._prepare_historical_graph_data(relevant_logs_data)
        return {
            "notes": feedback_notes,
            "actions": adjustments,
            "graph": master_graph_data, # Contient maintenant ror_mean, bt_mean, etc.
            "crashes": crashes_detected,
            "flicks": flicks_detected,
            "fc_bt_learned_c": fc_bt_learned_c,
            "fc_bt_samples": len(fc_samples_c),
            "fc_regression_slope": fc_regression_slope,   ## TILAU ## FC = a × Charge + b
            "fc_regression_offset": fc_regression_offset, ## TILAU ##
            "timing_dry_min_learned": timing_dry_learned,
            "timing_fc_min_learned": timing_fc_learned,
            "timing_samples": len(dry_time_samples_min),
            "drop_bt_learned_c": drop_bt_learned_c,
            "drop_bt_samples": len(drop_color_samples_c),
            "fc_bt_mad_c": fc_bt_mad_c,
            "drop_bt_mad_c": drop_bt_mad_c,
            "heater_dry_learned": heater_dry_learned,
            "heater_mai_learned": heater_mai_learned,
            "heater_dev_learned": heater_dev_learned,
            "heater_samples": heater_samples,
            "heater_fc_learned": heater_fc_learned,        ## TILAU ## item C
            "heater_fc_samples": len(heater_fc_samples),   ## TILAU ##
            "heater_de_learned": heater_de_learned,
            "heater_de_samples": len(heater_de_samples),
            "pre_de_lead_learned": pre_de_lead_learned,
            "pre_de_step_learned": pre_de_step_learned,
            "pre_de_descent_samples": len(pre_de_lead_samples),
            "dev_trajectory_learned": dev_trajectory_learned,
            "dev_traj_samples": dev_traj_n,
            "peak_ror_learned": peak_ror_learned,   ## TILAU ## setup loop
            "peak_ror_n": peak_ror_n,               ## TILAU ##
            "drop_ror_learned_c": _med(drop_ror_samples_c),   ## TILAU ## item A (Bench-Integration)
            "drop_ror_samples": len(drop_ror_samples_c),      ## TILAU ##
            }
        #return {"notes": feedback_notes, "actions": adjustments, "graph": self._prepare_historical_graph_data(relevant_logs_data), "crashes": crashes_detected, "flicks": flicks_detected}

    def _merge_events_by_phase(self, events_list, proximity_sec=30):
        """
        Groups events by phase first, then by time.
        """
        flattened = [item for sublist in events_list for item in sublist]
        if not flattened: return []

        # Sort by phase then by time
        flattened.sort(key=lambda x: (x.get('phase', ''), x['time']))

        merged = []
        current_group = []

        for item in flattened:
            if not current_group:
                current_group.append(item)
                continue
            
            prev = current_group[-1]
            # Check if same phase AND within time window
            if item['phase'] == prev['phase'] and (item['time'] - prev['time']) <= proximity_sec:
                current_group.append(item)
            else:
                merged_item = self._average_event_group(current_group)
                if merged_item: merged.append(merged_item)
                current_group = [item]
        
        if current_group:
            merged_item = self._average_event_group(current_group)
            if merged_item: merged.append(merged_item)

        return merged    
    
    def _adjust_deviation(self, bt_deviation: ProbeDeviation, roasting_plan: RoasterBasicPlan) -> RoasterBasicPlan:
        # Mean = (start_min + end_min) / 2
        mean_drop_dev = (bt_deviation.bt_at_drop.start_min + bt_deviation.bt_at_drop.end_min) / 2.0

        adjusted_phases = []
        plan_iterator = roasting_plan if isinstance(roasting_plan, list) else roasting_plan.plans

        for phase in plan_iterator:
            # Charge band is already expressed in measured BT (owner ruling
            # 2026-08-04) — it must NOT be shifted by the probe deviation.

            # Adjust Drop Temp: (min + mean, max + mean)
            new_drop_temp = (
                int(phase.drop_temp[0] + mean_drop_dev),
                int(phase.drop_temp[1] + mean_drop_dev)
            )

            adjusted_phase = RoasterBasicPlanPerPhase(
                name=phase.name,
                heater_cmfc=phase.heater_cmfc,
                charge_temp=phase.charge_temp,
                total_time=phase.total_time,
                drying_time=phase.drying_time,
                maillard_time=phase.maillard_time,
                development_time=phase.development_time,
                dtr_pct=phase.dtr_pct,
                drop_temp=new_drop_temp,
                fc_temp=phase.fc_temp,
                dry_temp=phase.dry_temp,
            )
            adjusted_phases.append(adjusted_phase)

        return RoasterBasicPlan(plans=adjusted_phases)

    def _calculate_rpm_percentage(self, rpm_target: float,
                               min_rpm_percent: float = None,
                               step_rpm_percent: float = None) -> str:
        """
        Convert an RPM target to a percentage string.
        When RoasterContext is available, delegates to ctx.rpm_to_percent()
        which handles clamping and step resolution in RPM space.
        The min_rpm_percent / step_rpm_percent parameters are used only
        in the no-context fallback path (e.g. unit tests, plan preview
        without a loaded roaster).
        """
        if self._roaster_ctx is not None:
            return self._roaster_ctx.rpm_to_percent(rpm_target)

        # ── Generic fallback (no roaster context) ────────────────────────
        _min_pct  = min_rpm_percent  if min_rpm_percent  is not None else 40.0
        _step_pct = step_rpm_percent if step_rpm_percent is not None else 5.0
        FALLBACK_MIN_RPM = 34.0
        FALLBACK_MAX_RPM = 68.0
        rpm = max(FALLBACK_MIN_RPM, min(FALLBACK_MAX_RPM, rpm_target))
        pct = (rpm - FALLBACK_MIN_RPM) / (FALLBACK_MAX_RPM - FALLBACK_MIN_RPM) * 100.0
        pct = round(pct / _step_pct) * _step_pct
        return f"{max(_min_pct, min(100.0, pct)):.0f}%"
    
    def _clamp_batch_weight(self, charge_weight: float) -> float:
        """
        Clamp charge_weight to the roaster's valid batch range.
        Uses RoasterContext when available, otherwise passes the value through.
        """
        if self._roaster_ctx is not None:
            return self._roaster_ctx.clamp_batch(charge_weight)
        return charge_weight
  
    def _get_agtron_category(self, agtron_input: int | float | AgtronScale) -> str:
        if hasattr(agtron_input, 'name') and not isinstance(agtron_input, (int, float)):
            return agtron_input.name
        try:
            val = float(agtron_input)
            for a in reversed(AGTRON_SCALES):
                if a.agtron_range.min_value <= val <= a.agtron_range.max_value:
                    return a.name
        except (ValueError, TypeError):
            pass
        return ""

    def _compute_ror_at_drop(
        self,
        agtron_ratio: float,        # 0.0 = dark (Agtron 30) → 1.0 = light (Agtron 75)
        dev_time_min: float,               # development phase duration in minutes
        ror_dev_avg: float,         # average RoR during development (°C/min)
        fc_bt: float,             # first crack temperature (°C)
        drop_bt_temperature: float,           # drop temperature (°C)
        charge_weight: float,       # batch weight in grams
        density: float,             # bean density in g/L
        water_activity: float = 0.0, # bean water activity (0.0 = not measured)
        nominal_weight_g: float = 500.0,  # roaster's reference batch weight
        heat_retention: float = 0.65,     # roaster heat_retention_index [0-1]
        is_fir_nir: bool = False,         ## TILAU ## item A : table par type de machine
    ) -> float:
        """
        Computes a physiologically coherent RoR at drop point.

        The RoR at drop is NOT simply ror_dev_avg - 1.0. It depends on:

        1. ROAST DEPTH (agtron_ratio):
            Light roasts are dropped while RoR is still relatively high (fast
            moving curve, flavor complexity preserved). Dark roasts need a much
            lower RoR at drop to prevent over-development momentum after drop.

        2. DEVELOPMENT PHASE DURATION (dev_time_min):
            A short dev phase means the curve hasn't decelerated much yet —
            RoR at drop is close to ror_dev_avg.
            A long dev phase allows more deceleration — RoR at drop is lower.

        3. THERMAL DELTA DURING DEVELOPMENT (drop_bt_temperature - fc_bt):
            The actual temperature rise during development constrains how fast
            RoR can decay. A small delta with a long dev_time_min = aggressive decay.
            A large delta = sustained RoR, less decay.

        4. THERMAL MASS (charge_weight, density):
            Heavier and denser loads retain heat longer — the deceleration of
            RoR is slower, meaning RoR at drop stays higher for a given dev_time_min.
            Light loads decelerate faster.

        5. WATER ACTIVITY (optional):
            High WA beans carry more latent moisture into development, which
            absorbs energy and causes a steeper RoR drop toward the end.
            Low WA beans behave more predictably.

        Returns
        -------
        float : RoR at drop in °C/min, clamped to [0.8, ror_dev_avg - 0.3].
        """

        # ── 1. ROAST DEPTH BASELINE — bonnes pratiques par TYPE de machine ────── ## TILAU ##
        # Item A (Bench-Integration-Spec, décision Tilau 2026-07-11) : sans
        # historique le plan suit les bonnes pratiques de la profession, PAR
        # type de machine. Les rapides FIR/NIR (roasts 8-12 min) droppent avec
        # un RoR bien plus vif que les tambours classiques : light 5,5 /
        # medium 5,0 / dark 4,0 °C/min (bande saine mesurée sur 52 roasts
        # Skywalker : médiane 5,2, P25-P75 4,1-6,9). Tambour classique
        # (conduction/convection, roasts plus longs) : light 3,5 / medium 3,0 /
        # dark 2,0. L'ancienne base 1,0-3,5 (doctrine tambour) produisait des
        # cibles 2-3x sous la réalité FIR (La Fabrica : cible 1,8 vs corpus 5,7)
        # et biaisait coach dev, countdown DROP, DTR projeté et popup pre-drop.
        if is_fir_nir:
            ROR_AT_DROP_DARK  = 4.0   # °C/min — FIR/NIR, dark
            ROR_AT_DROP_LIGHT = 5.5   # °C/min — FIR/NIR, light
        else:
            ROR_AT_DROP_DARK  = 2.0   # °C/min — tambour classique, dark
            ROR_AT_DROP_LIGHT = 3.5   # °C/min — tambour classique, light
        base_ror_at_drop = ROR_AT_DROP_DARK + (ROR_AT_DROP_LIGHT - ROR_AT_DROP_DARK) * agtron_ratio

        # ── 2. DEVELOPMENT DURATION DECELERATION ────────────────────────────────
        # Compute the mean deceleration rate from FC to drop.
        # If dev_time_min is short, actual deceleration is small (RoR barely drops from avg).
        # If dev_time_min is long, RoR has had time to fall significantly.
        #
        # We model the RoR decay as a fraction of ror_dev_avg based on how long
        # the development phase ran relative to its "natural" deceleration window.
        # Reference: a 2-minute dev phase allows full deceleration to target;
        # anything shorter preserves more of the initial RoR.
        REFERENCE_DEV_TIME = 2.0  # minutes — full deceleration reference
        decel_factor = min(1.0, dev_time_min / REFERENCE_DEV_TIME)  # 0.0 → 1.0

        # The actual deceleration from ror_dev_avg toward base_ror_at_drop
        # is scaled by how much time was available.
        decel_contribution = (ror_dev_avg - base_ror_at_drop) * decel_factor

        # ── 3. THERMAL DELTA CORRECTION ─────────────────────────────────────────
        # delta_T = drop_bt_temperature - fc_bt: the temperature rise during development.
        # A high delta with short dev_time_min means the curve is steep → RoR stays high.
        # A low delta with long dev_time_min means the curve is nearly flat → RoR is low.
        delta_T_dev = max(0.0, drop_bt_temperature - fc_bt)

        # Instantaneous RoR implied by the actual thermal curve shape:
        # ror_implied = delta_T / dev_time_min  (simple average slope of the dev phase)
        # We use this to anchor our estimate — the RoR at drop cannot be much
        # higher than the average slope of the whole development arc.
        ror_implied_avg = delta_T_dev / dev_time_min if dev_time_min > 0 else ror_dev_avg

        # Blend between the depth-based estimate and the curve-implied slope.
        # Weight: 30% implied (physics), 70% depth-based (style intent).
        ror_blended = 0.3 * ror_implied_avg + 0.7 * base_ror_at_drop

        # Apply the deceleration reduction on top of the blended estimate
        drop_ror = ror_blended - (decel_contribution * 0.5)

        # ── 4. THERMAL MASS ADJUSTMENT ──────────────────────────────────────────
        # Point 4: use roaster's nominal batch weight (from optimal_batch_capacity_g)
        # instead of the hardcoded 500 g reference, so the adjustment is zero at
        # the machine's intended operating point.
        # Point 5: scale the per-unit adjustment by heat_retention_index:
        #   high retention (cast-iron drum, e.g. Santoker 0.90) → RoR decelerates
        #   more slowly → higher RoR at drop for a given batch size.
        #   low retention  (fluid bed, e.g. IKAWA 0.20) → faster deceleration.
        NOMINAL_DENSITY = 700.0   # g/L (bean reference, not machine-specific)

        # Base weight adjustment scaled by retention index (higher retention = slower deceleration).
        # Coefficient 0.27 calibrated on 83 real roasts (r=0.46 batch_weight vs delta_temp_dev).
        weight_adj = ((charge_weight - nominal_weight_g) / 500.0) * 0.27 * heat_retention

        # Density adjustment (denser beans have more thermal inertia)
        density_adj = ((density - NOMINAL_DENSITY) / 50.0) * 0.08

        drop_ror += weight_adj + density_adj

        # ── 5. WATER ACTIVITY CORRECTION ────────────────────────────────────────
        # High WA: residual moisture absorbs heat in development → steeper RoR drop
        # Low WA:  dry beans transfer heat efficiently → more gradual RoR decay
        if water_activity > 0.0:
            WA_NEUTRAL = 0.60  # reference point: no correction
            wa_delta = water_activity - WA_NEUTRAL

            # Each 0.05 above neutral: -0.12°C/min at drop (moisture absorbs energy)
            # Each 0.05 below neutral: +0.08°C/min at drop (drier = less energy sink)
            if wa_delta > 0:
                wa_adj = -(wa_delta / 0.05) * 0.12
            else:
                wa_adj = -(wa_delta / 0.05) * 0.08  # wa_delta is negative → result positive

            drop_ror += wa_adj
            _logd.debug(
                f"WA correction: wa={water_activity:.3f}, delta={wa_delta:+.3f}, "
                f"adj={wa_adj:+.3f}°C/min"
            )

        # ── 6. FINAL BOUNDS ──────────────────────────────────────────────────────
        # Hard floor: RoR at drop must be positive (bean is still gaining heat
        # until it physically leaves the drum).
        # Hard ceiling: cannot exceed ror_dev_avg - 0.3 (must be decelerating
        # at least slightly — a flat or accelerating RoR at drop indicates
        # under-development, which we flag but still clamp).
        # Bande saine mesurée (FIR/NIR, corpus 52 roasts) : [3,5 ; 7,0] —      ## TILAU ##
        # les seuils de défaut de l'étude 3. Tambour classique : plancher 0,5.  ## TILAU ##
        ROR_DROP_FLOOR   = 3.5 if is_fir_nir else 0.5   # °C/min minimum (preferred)
        ROR_DROP_CEILING = ror_dev_avg - 0.3      # must be below dev average
        if is_fir_nir:
            ROR_DROP_CEILING = min(ROR_DROP_CEILING, 7.0)   ## TILAU ## bande saine

        # When ror_dev_avg is very low (< 0.8), the ceiling falls below the floor and
        # the old max(floor, min(ceiling, x)) returned the floor — i.e. a drop RoR
        # ABOVE the ceiling, silently breaking the "must be decelerating" guarantee.
        # Deceleration (staying below dev average) takes priority over the cosmetic
        # floor, so collapse the floor down to the ceiling when they cross.
        effective_floor = min(ROR_DROP_FLOOR, ROR_DROP_CEILING)
        drop_ror = max(effective_floor, min(ROR_DROP_CEILING, drop_ror))

        _logd.debug(
            f"drop_ror={drop_ror:.2f}°C/min "
            f"[base={base_ror_at_drop:.2f}, blended={ror_blended:.2f}, "
            f"decel={decel_contribution:.2f}, "
            f"mass_adj={weight_adj+density_adj:+.2f}]"
        )

        return round(drop_ror, 2)

    @staticmethod
    def _adopt_learned(grid_value: float, learned: float | None, n: int) -> tuple[float, str]:
        """
        Politique d'adoption progressive UNIQUE pour tout paramètre appris de
        l'historique (FC, durées de phase…) : n>=3 → médiane apprise telle
        quelle ; n==2 → blend 50/50 avec la chaîne grille ; sinon grille.
        Retourne (valeur, étiquette de source). Le caller reste responsable
        des bornes de plausibilité (passer learned=None si hors bornes).
        """
        if learned is not None:
            if n >= 3:
                return learned, f"learned (n={n})"
            if n == 2:
                return (learned + grid_value) / 2.0, "learned/grid blend (n=2)"
        return grid_value, "grid"

    @staticmethod
    def _build_pchip_curve(waypoints: list[dict]) -> dict:
        """
        PCHIP grids (1 s resolution) from explicit °C anchor waypoints.
        Shared by generate_bt_curve_waypoints (initial plan) and
        replan_from_milestone (mid-roast re-anchoring): both must produce
        the exact same curve structure so plan consumers cannot tell a
        re-fitted curve from an original one.
        """
        from scipy.interpolate import PchipInterpolator

        knot_t  = np.array([wp["time_min"] for wp in waypoints])
        knot_bt = np.array([wp["bt"]       for wp in waypoints])

        # Guard: knot times must be strictly increasing.
        # Clamp t_pre_drop if fc_time_min is very close to drop_time_min.
        if knot_t[-2] >= knot_t[-1]:
            knot_t[-2] = knot_t[-1] - 0.25

        pchip = PchipInterpolator(knot_t, knot_bt)

        # Evaluate at 1-second resolution
        time_grid = np.arange(0.0, knot_t[-1] + 1.0 / 60.0, 1.0 / 60.0)  # step = 1 s in minutes
        bt_grid   = pchip(time_grid)
        bt_grid   = np.clip(bt_grid, 20.0, knot_bt[-1] + 10.0)

        # ROR = first derivative of the PCHIP (°C/min)
        ror_grid = pchip.derivative()(time_grid)
        window_size = 30  # seconds
        if len(ror_grid) > window_size:
            kernel = np.ones(window_size) / window_size
            # use mode='edge' to avoid dropping data at start/end
            ror_grid = np.convolve(ror_grid, kernel, mode='same')
        ror_grid = np.clip(ror_grid, -2.0, 28.0)  # smooths numerical noise at endpoints

        return {
            "time_min":  time_grid.tolist(),
            "bt_plan":   np.round(bt_grid,  2).tolist(),
            "ror_plan":  np.round(ror_grid, 2).tolist(),
            "waypoints": waypoints,
        }

    # Seuils de la vérification RoR du Maillard — voir _maillard_conflict.
    _MAI_ROR_CRASH_C: Final[float] = 3.5    # °C/min : sous ce seuil le RoR s'effondre
    _OBSERVABLE_PCT:  Final[float] = 5.0    # jamais plus de 5 % à la fois…
    _OBSERVABLE_SEC:  Final[float] = 30.0   # …ni plus d'un cran par 30 s

    @classmethod
    def _maillard_conflict(cls, r_de_c: float, r_fc_c: float,
                           heater_drop_pct: float, maillard_time_min: float) -> str:
        """Le Maillard demandé est-il tenable ? "" si oui, sinon lequel des trois.

        Décision extraite en helper PUR parce qu'aucun plan du corpus ne la
        déclenche : laissée en ligne, elle n'aurait aucune couverture, et c'est
        précisément le code qui doit fonctionner le jour où le setup dérape.

        - `acceleration` : le RoR devrait MONTER pendant le Maillard — trop de
          degrés à couvrir dans le temps imparti, flick garanti.
        - `crash` : il s'effondre avant le FC — profil plat, pain grillé.
        - `illegible` : la descente de brûleur exigée dépasse ce qu'on peut
          voir (5 %/30 s) ; contrainte d'APPRENTISSAGE, pas de physique.

        Ordre volontaire : l'accélération et le crash disent que la géométrie
        elle-même est fausse ; l'illisibilité ne dit que l'inverse d'un feu
        initial trop haut. Un plan qui cumule les deux est d'abord un problème
        de géométrie.
        """
        if r_de_c <= 0.0:
            return ""          # pas de pente de référence : on se tait
        if r_fc_c >= r_de_c:
            return "acceleration"
        if r_fc_c < cls._MAI_ROR_CRASH_C:
            return "crash"
        allowed = (max(0.0, maillard_time_min) * 60.0
                   / cls._OBSERVABLE_SEC) * cls._OBSERVABLE_PCT
        if max(0.0, heater_drop_pct) > allowed:
            return "illegible"
        return ""

    @staticmethod
    def _planned_ror_at(curve: dict, t_min: float) -> float:
        """RoR (°C/min) de la courbe planifiée à un instant donné.

        Sert à lire R_DE — la pente RÉELLE à la sortie du séchage — au lieu d'une
        constante ou de la moyenne du séchage : le RoR décroît déjà pendant le
        séchage, sa moyenne surestimerait la valeur d'entrée du Maillard, et la
        vérification du Maillard y est très sensible. Renvoie 0.0 si la courbe
        est absente ou dégénérée (la vérification se tait alors).
        """
        try:
            times = curve["time_min"]
            rors  = curve["ror_plan"]
            if not times or not rors:
                return 0.0
            idx = min(range(len(times)), key=lambda i: abs(times[i] - float(t_min)))
            return max(0.0, float(rors[min(idx, len(rors) - 1)]))
        except (KeyError, TypeError, ValueError, IndexError):
            return 0.0

    @staticmethod
    def format_time(t: float) -> str:
        total_seconds = round(t * 60)
        minutes, seconds = divmod(total_seconds, 60)
        return f"{minutes:02d}:{seconds:02d}"

    def _verify_maillard_ror(self, *, curve: dict, dry_time_min: float,
                              maillard_time_min: float, ma_bt_temperature: float,
                              ror_maillard: float, heater_dry: float,
                              heater_pre_fc: float, ror_scale: float,
                              mode: str, decay_k: float) -> "tuple[float, str, str]":
        """Vérification RoR du Maillard (banc 2026-08-05).

        DERNIÈRE étape, et strictement DIAGNOSTIQUE. Les durées sont déjà
        fixées (dev → total → séchage → Maillard = reste) : on ne dérive JAMAIS
        une durée d'un RoR, ce serait remettre l'observable aux commandes.
        On lit ici ce que la géométrie retenue EXIGE, et on dit quand c'est
        intenable. Le plan ne résout pas le conflit — il signale que le setup
        était mauvais et limite les dégâts. Une réaction en chaîne ne se
        rattrape pas en cours de route.

          RoR(u) = R_FC + (R_DE − R_FC)·(1−u)^k     u = fraction du Maillard
          moyenne = R_FC + (R_DE − R_FC)/(k+1)
          R_FC    = (moyenne·(k+1) − R_DE)/k

        R_DE vient de la GÉOMÉTRIE RÉELLE du séchage — la pente de la courbe
        planifiée au jalon DRY END, pas une constante ni la moyenne du séchage
        (le RoR décroît déjà pendant le séchage, la moyenne le surestimerait).
        Le modèle y est très sensible.

        Renvoie (ror_fc_c, conflit, note) : `conflit` est "" | "acceleration" |
        "crash" | "illegible", `note` est le texte opérateur déjà formaté pour
        `conflit` ("" si aucun conflit).
        """
        _k: float = decay_k
        _r_de_c: float = self._planned_ror_at(curve, dry_time_min)
        ror_fc_c: float = ror_maillard
        if _r_de_c > 0.0 and _k > 0.0:
            ror_fc_c = (ror_maillard * (_k + 1.0) - _r_de_c) / _k
        _drop_required_pct = max(0.0, heater_dry - heater_pre_fc)
        _mai_conflict: str = self._maillard_conflict(
            _r_de_c, ror_fc_c, _drop_required_pct, maillard_time_min)
        note = ""
        if _mai_conflict:
            _logd.warning(
                f"RoastPlan: Maillard conflict [{_mai_conflict}] — R_DE {_r_de_c:.1f} → "
                f"R_FC {ror_fc_c:.1f}°C/min to cover {ma_bt_temperature:.1f}°C in "
                f"{maillard_time_min:.2f}min, burner down {_drop_required_pct:.0f}%. "
                f"The setup was wrong; the plan reports it and does not correct it.")
            note = {
                "acceleration": QApplication.translate(
                    "tilauscope_roast_plan",
                    "Setup conflict: covering {0}°{1} in {2} of Maillard would need the rate of rise to climb rather than fall. Expect a flick. Charge hotter or plan a longer Maillard next time — this roast cannot be recovered mid-way."),
                "crash": QApplication.translate(
                    "tilauscope_roast_plan",
                    "Setup conflict: the rate of rise has to fall to {3}°{1}/min before first crack to cover {0}°{1} in {2}. Expect a flat, bread-like cup. Charge cooler or shorten Maillard next time."),
                "illegible": QApplication.translate(
                    "tilauscope_roast_plan",
                    "Setup conflict: the burner would have to come down {4}% across a {2} Maillard — faster than you can see what you are doing. The initial heat setting was too high for this plan."),
            }[_mai_conflict].format(
                f"{ma_bt_temperature * ror_scale:.0f}", mode,
                self.format_time(maillard_time_min),
                f"{ror_fc_c * ror_scale:.1f}", f"{_drop_required_pct:.0f}")
        return ror_fc_c, _mai_conflict, note

    @staticmethod
    def _resolve_plan_confidence(
            *, fc_source: str, timing_source: str, drop_source: str,
            fc_bt_mad_c: "float | None",
            soak_dcharge_c: float, soak_dheater_pct: int,
            minutes_since_last_drop: "float | None", ror_scale: float,
    ) -> "_PlanConfidence":
        """Plan confidence & adaptive tolerances, and the heat-soak
        back-to-back operator note (design validé 2026-07-04, banc
        2026-08-05).

        Pure: no history, no ctx object — fc_bt_mad_c is read out of
        history at the call site, soak_dcharge_c/soak_dheater_pct out of
        the charge-setup stage's result, exactly like heater_max_pct in
        _resolve_burner_setpoints. Returns the confidence level, its
        tolerance factor, its translated display string, and the heat-soak
        note (None unless the correction is negative and a time since the
        last drop was supplied).
        """
        # ── Confiance du plan & seuils adaptatifs (design validé 2026-07-04) ─
        # Les sources (grid/blend/learned) et la dispersion MAD de l'historique
        # calibrent les seuils consommés par le coach (bandes RoR relatives) et
        # par le bilan d'adhérence EOR : un grain maîtrisé resserre (×0.8), un
        # plan grille relâche (×1.35), un historique fourni mais dispersé
        # (MAD FC > 2.5 °C — jalons mal marqués, lots hétérogènes) est
        # rétrogradé à medium.
        def _src_score(src: str) -> int:
            # « blend » d'abord : le label est "learned/grid blend (n=2)" —
            # startswith("learned") le classerait à tort comme learned plein.
            return 1 if "blend" in src else (2 if src.startswith("learned") else 0)
        _conf_score = _src_score(fc_source) + _src_score(timing_source) + _src_score(drop_source)
        _conf_level = ("low" if _conf_score == 0 else
                       "high" if _conf_score >= 4 else "medium")
        _fc_mad = fc_bt_mad_c
        if _conf_level == "high" and _fc_mad is not None and _fc_mad > 2.5:
            _conf_level = "medium"
        _tol_factor = {"low": 1.35, "medium": 1.0, "high": 0.8}[_conf_level]
        _conf_display = {
            "low":    QApplication.translate("tilauscope_roast_plan", "low (grid)"),
            "medium": QApplication.translate("tilauscope_roast_plan", "medium (partial history)"),
            "high":   QApplication.translate("tilauscope_roast_plan", "high (consistent history)"),
        }[_conf_level]
        _logd.info(f"RoastPlan: confidence={_conf_level} (score={_conf_score}, "
                   f"fc_mad={_fc_mad}) → tolerance ×{_tol_factor}")

        # Small-batch operator note removed 2026-08-04 along with the charge
        # pull-down it described (see the charge-band block above).

        # ── Heat-soak : note opérateur + clé machine (unités natives) ────────
        _soak_note: 'str | None' = None
        if soak_dcharge_c < 0.0 and minutes_since_last_drop is not None:
            _soak_note = QApplication.translate(
                "tilauscope_roast_plan",
                "Back-to-back ({0} min since last drop): charge {1}°, dry heater {2}%").format(
                f"{minutes_since_last_drop:.0f}",
                f"{soak_dcharge_c * ror_scale:+.1f}", f"{soak_dheater_pct:+d}")

        return _PlanConfidence(level=_conf_level, tol_factor=_tol_factor,
                                display=_conf_display, soak_note=_soak_note)

    @staticmethod
    def _water_activity_effect(water_activity: float) -> "_WaterActivityEffect":
        """Deltas from GreenBean.water_activity (banc 2026-08-05).

        WA = 0.0 means not measured; only apply when a real reading is
        available. Ideal storage WA is 0.55–0.65. Above 0.65 = moisture risk
        (more drying energy needed). Below 0.55 = over-dried (faster drying,
        lower charge temp adjustment). The two branches are mutually
        exclusive and touch disjoint fields: the high branch never moves the
        charge temperature, the low branch never touches heater/airflow/
        extraction.
        """
        wa = water_activity
        if wa > 0.0:  # Only when actually measured
            if wa > 0.65:
                wa_excess:float = wa - 0.65
                # Each 0.05 above 0.65 adds ~0.2 min drying, 2% heater, 3% airflow
                wa_factor:float = wa_excess / 0.05
                _logd.debug(
                    f"WA={wa:.3f} (high): dry_time_min +{wa_factor*0.2:.2f}min, "
                    f"heater +{wa_factor*2:.1f}%, airflow +{wa_factor*3:.1f}%"
                )
                return _WaterActivityEffect(
                    d_dry_time_min=wa_factor * 0.20,          # extend drying phase
                    d_heater_dry_pct=wa_factor * 2.0,  # boost heater during dry
                    d_airflow_pct=wa_factor * 1.5,   # modéré : max +3% pour WA=0.75
                    d_extraction_pct=wa_factor * 2.0,   # modéré : max +4% pour WA=0.75
                )
            elif wa < 0.55:
                wa_deficit:float = 0.55 - wa
                wa_factor:float = wa_deficit / 0.05
                _logd.debug(
                    f"WA={wa:.3f} (low): dry_time_min -{wa_factor*0.15:.2f}min, "
                    f"charge temp -{wa_factor*1.5:.1f}°C"
                )
                return _WaterActivityEffect(
                    d_dry_time_min=-wa_factor * 0.15,
                    d_charge_c=-wa_factor * 1.5,
                )
        return _WaterActivityEffect()

    @staticmethod
    def _charge_setup(*, process_type_lower: str, density: "float | None",
                       culture_altitude: "float | None", humidity: "float | None",
                       ambient_temp_c: "float | None",
                       minutes_since_last_drop: "float | None",
                       thermal_mass_idx: float, heat_retention_idx: float) -> "_ChargeSetup":
        """Charge band by PROCESS, bean/ambient modulation, and inter-batch
        heat-soak correction (banc 2026-08-05) — owner ruling 2026-08-04 on
        the doctrine (process sets the band, batch weight is deliberately
        absent from both the band and the modulation).

        Pure: no history, no ctx object. Returns the band and the
        pre-modulation midpoint alongside the final temperature — see
        _ChargeSetup for why both survive the stage.
        """
        # ── Charge band by PROCESS (owner ruling 2026-08-04) ────────────────
        # The process sets the band, in measured BT. Roast level, batch weight
        # and learned history no longer touch the charge. Modulation by bean and
        # ambient constants is applied below, capped at ±_CHARGE_MODULATION_MAX_C.
        # Decaf is tested first: it is the most specific label and can co-occur
        # with a process word ("decaf washed").
        if "decaf" in process_type_lower or "decaffeinated" in process_type_lower:
            _charge_band = _CHARGE_BAND_BY_PROCESS["decaf"]
        elif ("honey" in process_type_lower or "pulped natural" in process_type_lower
              or "wet hulled" in process_type_lower or "natural" in process_type_lower
              or "dry process" in process_type_lower or "anaerobic" in process_type_lower
              or "fermentation" in process_type_lower or "fermented" in process_type_lower
              or "carbonic" in process_type_lower or "maceration" in process_type_lower
              or "yeast" in process_type_lower):
            # Fermented/anaerobic processes group with the naturals: they carry
            # the same surface sugars from extended contact with the mucilage/fruit.
            _charge_band = _CHARGE_BAND_BY_PROCESS["natural"]
        else:
            _charge_band = _CHARGE_BAND_BY_PROCESS["washed"]
        _charge_temperature: float = _mean(_charge_band[0], _charge_band[1])

        # ── Modulation by bean and ambient constants, capped ────────────────
        # Only a few degrees of authority: the band is the doctrine, these
        # constants brush around it. Batch weight is deliberately absent — a
        # small batch charges at the SAME temperature (owner ruling 2026-08-04).
        # Each input is gated on a plausibility window first: the corpus has
        # sensor/entry errors (ambientTemp 526°C, 555°C) that used to saturate
        # this modulation at its cap with no warning — out-of-window readings
        # now contribute 0 instead.
        def _plausible(value: "float | None", lo: float, hi: float, label: str) -> "float | None":
            # 0.0 is the codebase-wide "not measured" sentinel for density and
            # humidity — absent, not implausible. Silent, or every plan for a bean
            # without a density reading would log a warning.
            if value is None or float(value) == 0.0:
                return None
            if not (lo <= float(value) <= hi):
                _logd.warning(f"RoastPlan: {label} {float(value):.1f} out of plausible "
                              f"range [{lo:g}, {hi:g}] — ignored for the charge modulation")
                return None
            return float(value)

        _density_ok  = _plausible(density, 250.0, 1000.0, "bean density")
        _altitude_ok = _plausible(culture_altitude, 0.0, 3500.0, "altitude")
        _humidity_ok = _plausible(humidity, 5.0, 20.0, "bean humidity")
        _ambient_ok  = _plausible(ambient_temp_c, -10.0, 60.0, "ambient temperature")

        _mod_density  = ((_density_ok - 700.0) / 50.0) * 2.0 if _density_ok is not None else 0.0
        _mod_altitude = float(max(0.0, _altitude_ok - 1000.0)) / 200.0 if _altitude_ok is not None else 0.0
        _mod_humidity = (_humidity_ok - 11.0) * 0.5 if _humidity_ok is not None else 0.0
        _mod_ambient  = (20.0 - _ambient_ok) * 0.2 if _ambient_ok is not None else 0.0
        _charge_modulation = _clamp(
            _mod_density + _mod_altitude + _mod_humidity + _mod_ambient,
            -_CHARGE_MODULATION_MAX_C, _CHARGE_MODULATION_MAX_C)
        charge_bt_temperature: float = _clamp(
            _charge_temperature + _charge_modulation, _charge_band[0], _charge_band[1])
        _logd.info(
            f"RoastPlan: charge {charge_bt_temperature:.1f}°C — band {_charge_band} "
            f"({process_type_lower or 'washed default'}), modulation "
            f"{_charge_modulation:+.1f}°C (density {_mod_density:+.1f}, altitude "
            f"{_mod_altitude:+.1f}, humidity {_mod_humidity:+.1f}, ambient {_mod_ambient:+.1f})")

        # Setup loop on peak RoR removed 2026-08-04: it corrected the charge from
        # an observable dominated by batch mass, and learned from a corpus the plan
        # itself had produced. The charge is doctrine-driven now.

        # Small-batch charge pull-down removed 2026-08-04 (owner ruling): a small
        # batch charges at the SAME temperature — that is precisely what lets it
        # reach a higher turning point and dry faster.

        # ── Heat-soak inter-batch (design validé 2026-07-04) ────────────────
        # Batch 2+ : appliqué APRÈS le clamp grille — la correction doit
        # pouvoir passer sous le plancher de la grille (c'est son objet).
        # Le heater dry est corrigé plus bas, au moment de son calcul.
        _soak_dcharge_c: float = 0.0
        _soak_dheater: int = 0
        _soak_tau: float = 0.0
        if minutes_since_last_drop is not None and minutes_since_last_drop >= 0.0:
            _soak_dcharge_c, _soak_dheater, _soak_tau = heat_soak_correction(
                minutes_since_last_drop, thermal_mass_idx, heat_retention_idx)
            if _soak_dcharge_c < 0.0:
                charge_bt_temperature = max(120.0, charge_bt_temperature + _soak_dcharge_c)
                _logd.info(
                    f"RoastPlan: heat soak — charge {_soak_dcharge_c:+.1f}°C, dry heater "
                    f"{_soak_dheater:+d}% ({minutes_since_last_drop:.0f} min since drop, τ={_soak_tau:.0f} min)")

        return _ChargeSetup(
            band=_charge_band, nominal_temperature_c=_charge_temperature,
            temperature_c=charge_bt_temperature, soak_dcharge_c=_soak_dcharge_c,
            soak_dheater_pct=_soak_dheater, soak_tau_min=_soak_tau)

    @staticmethod
    def _base_phase_durations(*, roast_constraints: RoasterBasicPlanPerPhase,
                               density: float, humidity: float) -> "tuple[float, float, float]":
        """Nominal total/drying/development durations, before water-activity
        and cross-roast calibration are applied (banc 2026-08-05).

        Development is grouped in here even though the original code computed
        it further down, at the top of the calibration block: it depends only
        on roast_constraints, same as total and drying, and grouping the
        three base durations together is the point of this stage. Pure — it
        does not read anything written between its old position and here.

        Returns (total_time_min, dry_time_min, dev_time_min).
        """
        # time of phases in fraction of minutes
        # ── Phase timings anchored on TOTAL (owner ruling 2026-08-04) ───────
        # Standard practice: drying is ~50% of the roast, development is the
        # professional absolute-duration band for the target level (see below),
        # Maillard is the remainder. The per-phase grid tuples are kept only as
        # sanity bounds, no longer as the source of the durations.
        total_time_min: float = _mean(roast_constraints.total_time[0], roast_constraints.total_time[1])
        dry_time_min: float = (total_time_min * _DRY_SHARE
                               + (density - 700) / 200.0 * 0.3
                               + (humidity - 12.0) * 0.12)

        # Development is an absolute DURATION, taken from the professional band
        # for the target roast level — not derived from a DTR target. The ratio is
        # a consequence of the whole roast, reported below, never the driver
        # (same doctrine as the rate of rise: settings are the cause).
        dev_time_min: float = _mean(roast_constraints.development_time[0], roast_constraints.development_time[1])
        return total_time_min, dry_time_min, dev_time_min

    def _calibrate_and_floor_phase_durations(
            self, *, dry_time_min: float, total_time_min: float, dev_time_min: float,
            drying_time_band: "tuple[float, float]", maillard_time_band: "tuple[float, float]",
            t_dry_raw: "float | None", t_fc_raw: "float | None", t_n: int,
    ) -> "_PhaseDurationCalibration":
        """Cross-roast timing calibration, then the physical duration floors
        (banc 2026-08-05).

        ORDER IS THE POINT: the floors run AFTER the learned calibration —
        see the comment on the floors block below for why an inversion would
        let an unreachable value through. Pure: takes the water-activity-
        adjusted dry_time_min and the raw learned samples, returns the final
        durations plus what the calibration produced (source label, the two
        heater nudges, and the operator notes — the caller appends those to
        history["actions"], exactly like _verify_maillard_ror's note).
        """
        # ── Cross-roast timing calibration (per bean × machine) ─────────────
        # Learned realized phase timings from the historical cohort (medians
        # of computed.DRY_time / FCs_time collected by _analyze_historical_roasts).
        # Descriptive part: the planned durations follow the machine's real
        # behaviour, clamped to the grid style window ±0.5 min so the plan
        # stays within professional canons (adoption policy identical to the
        # learned FC: n>=3 median, n==2 blend 50/50 with the adjusted grid).
        # Prescriptive part: when the RAW learned duration sits outside the
        # strict style window, nudge the phase heater (bounded ±5%, 3%/min,
        # n>=3 only) to close the physical gap — and tell the user why.
        maillard_time_min: float = max(2.0, total_time_min - dry_time_min - dev_time_min)
        timing_source: str = "grid"
        _cal_heater_dry: float = 0.0
        _cal_heater_mai: float = 0.0
        _notes: list[str] = []
        if (t_dry_raw is not None and t_fc_raw is not None and t_n >= 2
                and 2.5 <= t_dry_raw <= 8.0
                and 2.0 <= (t_fc_raw - t_dry_raw) <= 7.0):
            _mai_raw = t_fc_raw - t_dry_raw
            _WINDOW_MARGIN = 0.5   # min of personalisation around the style window
            _dry_cal = _clamp(t_dry_raw, drying_time_band[0] - _WINDOW_MARGIN,
                              drying_time_band[1] + _WINDOW_MARGIN)
            _mai_cal = _clamp(_mai_raw, maillard_time_band[0] - _WINDOW_MARGIN,
                              maillard_time_band[1] + _WINDOW_MARGIN)
            # Shared progressive-adoption policy (same as the learned FC).
            dry_time_min, timing_source = self._adopt_learned(dry_time_min, _dry_cal, t_n)
            maillard_time_min, _        = self._adopt_learned(maillard_time_min, _mai_cal, t_n)
            _logd.info(
                f"RoastPlan: phase timing from history dry={dry_time_min:.2f}min "
                f"maillard={maillard_time_min:.2f}min [{timing_source}]")
            if t_n >= 3:
                _HEATER_PER_MIN = 3.0   # % per minute outside the style window
                _HEATER_CAP     = 5.0   # % absolute cap
                _dry_gap = t_dry_raw - _clamp(t_dry_raw, drying_time_band[0], drying_time_band[1])
                if abs(_dry_gap) > 0.3:
                    _cal_heater_dry = _clamp(_dry_gap * _HEATER_PER_MIN, -_HEATER_CAP, _HEATER_CAP)
                    _notes.append(QApplication.translate(
                        "tilauscope_roast_plan",
                        "Calibration: this bean's drying runs {0} min on this machine (plan window {1}-{2}) — dry heater adjusted {3}%").format(
                        f"{t_dry_raw:.1f}", f"{drying_time_band[0]:.2g}",
                        f"{drying_time_band[1]:.2g}", f"{_cal_heater_dry:+.0f}"))
                _mai_gap = _mai_raw - _clamp(_mai_raw, maillard_time_band[0], maillard_time_band[1])
                if abs(_mai_gap) > 0.3:
                    _cal_heater_mai = _clamp(_mai_gap * _HEATER_PER_MIN, -_HEATER_CAP, _HEATER_CAP)
                    _notes.append(QApplication.translate(
                        "tilauscope_roast_plan",
                        "Calibration: this bean's Maillard runs {0} min on this machine (plan window {1}-{2}) — Maillard heater adjusted {3}%").format(
                        f"{_mai_raw:.1f}", f"{maillard_time_band[0]:.2g}",
                        f"{maillard_time_band[1]:.2g}", f"{_cal_heater_mai:+.0f}"))

        # ── Garde-fous PHYSIQUES de durée (arbitrés 2026-08-05) ───────────────
        # Ils viennent de la MACHINE, pas de la grille de style, donc ils passent
        # APRÈS la calibration apprise : sa fenêtre d'adoption laisse entrer un
        # séchage de 2,5 min, physiquement hors d'atteinte sur un tambour de cette
        # taille (c'est le domaine des torréfacteurs d'échantillon).
        # Chaque phase est bornée SÉPARÉMENT, jamais l'une aux dépens de l'autre :
        # le total est la somme des trois (calculé plus bas), donc c'est LUI qui
        # s'allonge quand un garde-fou mord. Recalculer le Maillard par
        # soustraction ici écraserait la durée apprise de l'historique.
        _DRY_MIN_MIN: float = 4.5    # 4:30 — en dessous, séchage hors d'atteinte
        _MAI_MIN_MIN: float = 3.0    # 3:00 — en dessous, il faudrait brûler le grain
        if dry_time_min < _DRY_MIN_MIN:
            _logd.warning(
                f"RoastPlan: planned drying {dry_time_min:.2f}min is below the "
                f"machine floor {_DRY_MIN_MIN:.2f}min — raised; the total extends")
            dry_time_min = _DRY_MIN_MIN
        if maillard_time_min < _MAI_MIN_MIN:
            _logd.warning(
                f"RoastPlan: planned Maillard {maillard_time_min:.2f}min is below "
                f"the machine floor {_MAI_MIN_MIN:.2f}min — raised; the total extends")
            maillard_time_min = _MAI_MIN_MIN

        return _PhaseDurationCalibration(
            dry_time_min=dry_time_min, maillard_time_min=maillard_time_min,
            timing_source=timing_source, cal_heater_dry_pct=_cal_heater_dry,
            cal_heater_mai_pct=_cal_heater_mai, notes=_notes)

    def _resolve_drop_and_dev_ror(
            self, *, drop_bt_temperature: float, drop_min: float, drop_max: float,
            drop_learned_c: "float | None", drop_samples: int,
            drop_ror_learned_c: "float | None", drop_ror_samples: int,
            fc_bt: float, dev_time_min: float,
            dev_ror_expected: float, agtron_ratio: float, charge_weight: float,
            density: float, water_activity: float, nominal_weight_g: float,
            heat_retention: float, is_fir_nir: bool,
    ) -> "_DropAndDevRor":
        """Learned-drop adoption from measured colours, the FC→DROP coherence
        rebuild, and the development/drop RoR derivation (banc 2026-08-05).

        Pure: takes the grid+inertia drop estimate and the style band, returns
        the final drop BT and its source, the development RoR, the RoR at
        drop, and the operator notes for the caller to append to
        history["actions"] — exactly like _verify_maillard_ror's note.
        """
        # ── Learned drop from measured colours (design validé 2026-07-04) ───
        # When the bean's history carries measured colours, the median drop BT
        # corrected to the current target colour REPLACES the grid+inertia
        # estimate (same progressive-adoption policy as the learned FC).
        # Clamped to the style band ±3 °C: a biased history (moved probe,
        # atypical lot) can never pull the plan out of the target style.
        drop_source = "grid"
        _notes: "list[str]" = []
        _drop_raw = drop_learned_c
        _drop_n   = int(drop_samples or 0)
        if _drop_raw is not None and (drop_min - 8.0) <= float(_drop_raw) <= (drop_max + 8.0):
            _drop_cal  = _clamp(float(_drop_raw), drop_min - 3.0, drop_max + 3.0)
            _drop_grid = drop_bt_temperature
            drop_bt_temperature, drop_source = self._adopt_learned(
                drop_bt_temperature, _drop_cal, _drop_n)
            if drop_source != "grid":
                _notes.append(QApplication.translate(
                    "tilauscope_roast_plan",
                    "Colour feedback ({0} measured roast(s)): drop target adjusted {1}°C vs grid ({2}°)").format(
                    _drop_n, f"{drop_bt_temperature - _drop_grid:+.1f}", f"{_drop_grid:.1f}"))
                _logd.info(
                    f"RoastPlan: drop from colour history {drop_bt_temperature:.1f}°C "
                    f"[{drop_source}] (grid {_drop_grid:.1f}°C, n={_drop_n})")

        # ── Cohérence FC → DROP (fix 2026-08-04) ─────────────────────────────
        # L'ancre FC peut être APPRISE (BT mesuré brut) pendant que la bande de
        # drop vient de la grille corrigée de la déviation sonde : les deux
        # référentiels peuvent se croiser et produire drop_bt < fc_bt, une
        # géométrie physiquement impossible qui écrasait dev_ror sur son plancher
        # et sortait un RoR au drop de 0,2 °C/min. Dès que le drop passe sous la
        # pente de développement minimale, c'est la pente qui fait autorité :
        # on reconstruit le drop depuis l'ancre FC.
        _dev_ror_floor = dev_ror_expected * 0.8       # pente dev minimale théorique
        _drop_coherent = fc_bt + _dev_ror_floor * dev_time_min
        if drop_bt_temperature < _drop_coherent:
            _logd.warning(
                f"RoastPlan: drop {drop_bt_temperature:.1f}°C incohérent avec FC "
                f"{fc_bt:.1f}°C sur {dev_time_min:.2f} min — reconstruit à "
                f"{_drop_coherent:.1f}°C (pente dev min {_dev_ror_floor:.1f}°C/min)")
            # The reconstruction may never leave the style band (fix 2026-08-05):
            # unbounded, it pushed a Medium Light plan to 203.2 °C when the band
            # tops out at 200.5. If the ceiling binds, the learned first crack sits
            # too high for the target level — say so rather than drift the colour.
            if _drop_coherent > drop_max:
                _logd.warning(
                    f"RoastPlan: drop coherence {_drop_coherent:.1f}°C above the "
                    f"style ceiling {drop_max:.1f}°C — capped; learned FC "
                    f"{fc_bt:.1f}°C is high for this roast level")
                _drop_coherent = drop_max
            drop_bt_temperature = round(_drop_coherent, 1)
            drop_source = "coherence"

        # GEOMETRY-DERIVED development average RoR: the real slope between the FC
        # and drop anchors over the development duration. Single value used both
        # for display and to place the pre-drop waypoint, so the dev segment is
        # self-consistent (no kink, no displayed/actual mismatch). °C/min.
        dev_ror:float = (drop_bt_temperature - fc_bt) / dev_time_min if dev_time_min > 0 else dev_ror_expected
        # keep the theoretical minimum development slope as the floor (fix 2026-08-04:
        # replaces the old cosmetic 0.5 floor, which masked the FC/drop mismatch above)
        dev_ror = max(_dev_ror_floor, dev_ror)

        drop_ror = self._compute_ror_at_drop(
            agtron_ratio    = agtron_ratio,
            dev_time_min           = dev_time_min,
            ror_dev_avg     = dev_ror,
            fc_bt         = fc_bt,
            drop_bt_temperature       = drop_bt_temperature,
            charge_weight   = charge_weight,
            density         = density,
            water_activity  = water_activity,
            nominal_weight_g= nominal_weight_g,        # Point 2+4: roaster-aware nominal
            heat_retention   = heat_retention,          # Point 4: thermal index
            is_fir_nir      = is_fir_nir,               ## TILAU ## item A : table par type
        )
        # ── RoR au drop APPRIS de l'historique du grain (item A, Bench-Integration) ## TILAU ##
        # Cohorte couleur-assortie, médiane, politique _adopt_learned habituelle
        # (n>=3 tel quel, n=2 blend, sinon table bonnes-pratiques ci-dessus).
        # Plausibilité [1,0 ; 9,0] °C/min ; le plafond de décélération
        # dev_ror − 0.3 PRIME sur l'appris (garantie « courbe encore
        # décélérante » — un appris au-dessus se fait clipper, c'est voulu).
        _dror_lrn = drop_ror_learned_c
        _dror_n = int(drop_ror_samples or 0)
        if _dror_lrn is not None and not (1.0 <= float(_dror_lrn) <= 9.0):
            _logd.debug(f"RoastPlan: drop RoR learned {_dror_lrn} out of plausibility [1,9] — ignored")
            _dror_lrn = None
        drop_ror, drop_ror_source = self._adopt_learned(
            drop_ror, float(_dror_lrn) if _dror_lrn is not None else None, _dror_n)
        drop_ror = round(min(drop_ror, dev_ror - 0.3), 2)
        if drop_ror_source != "grid":
            _logd.info(f"RoastPlan: drop RoR from history {drop_ror:.2f}°C/min "
                       f"[{drop_ror_source}] (n={_dror_n})")

        return _DropAndDevRor(
            drop_bt_temperature=drop_bt_temperature, drop_source=drop_source,
            dev_ror=dev_ror, drop_ror=drop_ror, drop_ror_source=drop_ror_source,
            notes=_notes)

    def _resolve_burner_setpoints(
            self, *, humidity: float, ambient_humidity: float,
            is_light_roast: bool, is_fir_nir: bool, agtron_mean: float,
            process_type_lower: str, process_type: str,
            density: "float | None", bean_varieties: str, bean_country: str,
            water_activity: "float | None", ambient_temp_c: "float | None",
            roast_constraints: RoasterBasicPlanPerPhase,
            cal_heater_dry_pct: float, cal_heater_mai_pct: float,
            soak_dheater_pct: int, heater_max_pct: float,
            heater_samples: int, heater_dry_learned: "float | None",
            heater_mai_learned: "float | None", heater_dev_learned: "float | None",
            heater_fc_learned: "float | None", heater_fc_samples: int,
    ) -> "_BurnerSetpoints":
        """Grid base by process/humidity, learned heater profile adoption, the
        Maillard energy floor, and the learned pre-FC setpoint (banc
        2026-08-05).

        Pure: no history, no ctx object. Returns the final dry/Maillard/dev/
        pre-FC setpoints, their sources, the floor profile and the machine
        ceiling (both still needed by the caller further down), the
        pre-floor development setpoint (for the caller's later Dev Ramp
        coherence recalculation), and the operator notes for the caller to
        append to history["actions"] — exactly like _resolve_drop_and_dev_ror.
        """
        # Dynamic Machine Controls (Heater/Airflow/Extraction) => % compensation
        heater_compensation:float = 0.0
        if humidity > 11.5:
            heater_compensation += 5.0
        if ambient_humidity > 70.0:
            heater_compensation += 5.0

        if is_light_roast and is_fir_nir: # 2026/02/18 fix specific light roast settings for FIR and NIR heaters
            # Values reduced 2026-08-04: the FIR/NIR radiant correction is already
            # carried by the heater_cmfc base further up (0.85/0.70/0.50 →
            # 0.60/0.55/0.50 for light roasts), so applying the old -20/-15/-25 here
            # double-counted the same correction and pushed the plan (45/40/35%)
            # well below the operator's real hand (65/60/50%).
            HDB_WASHED = 0.0
            HDB_NATURAL = -5.0
            HDB_DECAF = -10.0
        elif agtron_mean > 70.0:
            HDB_WASHED = 0.0
            HDB_NATURAL = -5.0
            HDB_DECAF = -5.0
        else:
            HDB_WASHED = -5.0
            HDB_NATURAL = -10.0
            HDB_DECAF = -15.0

        if "washed" in process_type_lower or "honey" in process_type_lower:
            heater_dry_process = HDB_WASHED
        elif "decaf" in process_type_lower or "decaffeinated" in process_type_lower:
            heater_dry_process = HDB_DECAF
        else: # Naturals/Other
            heater_dry_process = HDB_NATURAL

        # Use roast_constraints to cap power usage based on category
        HEATER_C, HEATER_M, HEATER_FC = roast_constraints.heater_cmfc[0], roast_constraints.heater_cmfc[1], roast_constraints.heater_cmfc[2]

        # Grid base (fallback) — process/humidity/timing-calibration corrections.
        _grid_dry:float = (HEATER_C * 100.0) + heater_dry_process + heater_compensation + cal_heater_dry_pct
        _grid_mai:float = (HEATER_M * 100.0) + heater_dry_process + heater_compensation + cal_heater_mai_pct
        _grid_dev:float = (HEATER_FC * 100.0) + heater_dry_process + heater_compensation

        # ── Learned heater profile (design validé 2026-07-04, #5) ────────────
        # Median burner % actually held per phase on colour-matched history
        # REPLACES the grid base (same progressive-adoption policy as FC/drop).
        # The learned value already embodies the operator's process/humidity/
        # altitude compensation on THIS machine — re-adding the grid corrections
        # would double-count, so at n≥3 the corrections are dropped (n=2 keeps
        # half via the blend). Heat-soak stays on top (batch-specific, absent
        # from the mostly-batch-1 history).
        heater_source = "grid"
        _h_n = int(heater_samples or 0)
        _hl_dry = heater_dry_learned
        _hl_mai = heater_mai_learned
        _hl_dev = heater_dev_learned
        _notes: "list[str]" = []
        if None not in (_hl_dry, _hl_mai, _hl_dev) and _h_n >= 2:
            heater_dry, heater_source = self._adopt_learned(_grid_dry, float(_hl_dry), _h_n)
            heater_maillard, _        = self._adopt_learned(_grid_mai, float(_hl_mai), _h_n)
            heater_dev, _             = self._adopt_learned(_grid_dev, float(_hl_dev), _h_n)
            if heater_source != "grid":
                _notes.append(QApplication.translate(
                    "tilauscope_roast_plan",
                    "Heater profile learned from {0} matched roast(s): {1}/{2}/{3}% (dry/Maillard/dev)").format(
                    _h_n, f"{heater_dry:.0f}", f"{heater_maillard:.0f}", f"{heater_dev:.0f}"))
                _logd.info(f"RoastPlan: heater from history {heater_dry:.0f}/{heater_maillard:.0f}/"
                           f"{heater_dev:.0f}% [{heater_source}] (n={_h_n})")
        else:
            heater_dry, heater_maillard, heater_dev = _grid_dry, _grid_mai, _grid_dev

        # Heater ceiling: hardware limit, not a style choice — some elements
        # (e.g. the ITOP Cyberroaster's FIR/NIR emitter) degrade above a
        # machine-specific power fraction, so the upper clamp bound is read
        # from the roaster context instead of a fixed 100.0.
        _heater_max_pct: float = heater_max_pct

        # Heat-soak (batch-specific) applied on top of either base; clamp 0–ceiling.
        heater_dry      = _clamp(heater_dry + soak_dheater_pct, 0.0, _heater_max_pct)
        heater_maillard = _clamp(heater_maillard, 0.0, _heater_max_pct)
        heater_dev      = _clamp(heater_dev, 0.0, _heater_max_pct)

        # ── PLANCHER DE MAILLARD — demande énergétique du grain ────────────────
        # Maillard est ENDOTHERMIQUE : baisser le brûleur n'y ralentit pas la
        # réaction, ça l'affame. La température continue de monter sur la masse
        # thermique et le RoR reste beau pendant que la chimie décroche — le
        # défaut « ça mijote » (baked). Le RoR est donc AVEUGLE ici : le contrôle
        # porte sur la trajectoire de réglage, pas sur la courbe.
        # Le plancher n'est ni un nombre ni un palier : c'est une COURBE issue du
        # grain (process → variété/terroir → constantes physiques → ambiance),
        # tenue à plat puis relâchée quand l'exothermie prend le relais.
        # Tables et justification chimique : tilauscope/bean_energy.py,
        # spec wiki/BeanEnergy-MaillardFloor-Spec.md.
        _floor: FloorProfile = maillard_floor(
            BeanProps(process=process_type,
                      varieties=bean_varieties,
                      country=bean_country,
                      density_g_l=density,
                      humidity_pct=humidity,
                      water_activity=water_activity),
            Ambient(temp_c=ambient_temp_c, humidity_pct=ambient_humidity))
        if _floor.unresolved:
            _logd.info("RoastPlan: Maillard floor — unrecognised label(s) %s, "
                       "treated as neutral", ", ".join(_floor.unresolved))
        # Le plancher ne RÉSOUT pas un conflit, il dit ce qu'il aurait fallu tenir.
        # Il ne peut que RELEVER une consigne, jamais l'abaisser (max).
        _h_mai_free, _h_dev_free = heater_maillard, heater_dev
        # Le séchage aussi : une consigne de séchage déjà sous la demande du grain
        # entre en Maillard affamé. Cas dégénéré (jamais rencontré sur le corpus),
        # mais l'escalier suppose une descente monotone — sans ce garde-fou la
        # courbe effective remonterait d'un cran au DRY END.
        _h_dry_free = heater_dry
        heater_dry = _clamp(max(heater_dry, _floor.level_pct), 0.0, _heater_max_pct)
        if heater_dry > _h_dry_free + 0.5:
            _logd.warning(f"RoastPlan: drying heater {_h_dry_free:.0f}% is below the "
                          f"bean energy floor {_floor.level_pct:.0f}% — raised; the "
                          f"grain would enter Maillard already starved")
        heater_maillard = _clamp(max(heater_maillard, _floor.at(0.5)), 0.0, _heater_max_pct)
        if heater_maillard > _h_mai_free + 0.5:
            _logd.info(f"RoastPlan: Maillard heater raised {_h_mai_free:.0f}→"
                       f"{heater_maillard:.0f}% by the bean energy floor "
                       f"(level {_floor.level_pct:.0f}%, release "
                       f"{_floor.release_fraction:.2f})")

        heater_tp:float          = heater_dry - (5.0 if not is_light_roast else 8.0)

        # ── Feu au FC appris — palier pre-FC de la rampe (item C, décision ────── ## TILAU ##
        # Tilau : FC appris de l'historique, backup = calcul actuel du plan,
        # c'est-à-dire la colonne dev comme avant). Cohorte couleur-assortie,
        # politique _adopt_learned habituelle, plausibilité [0,100].
        _hl_fc = heater_fc_learned
        _h_fc_n = int(heater_fc_samples or 0)
        if _hl_fc is not None and not (0.0 <= float(_hl_fc) <= 100.0):
            _hl_fc = None
        heater_pre_fc, heater_fc_source = self._adopt_learned(
            float(heater_dev), float(_hl_fc) if _hl_fc is not None else None, _h_fc_n)
        heater_pre_fc = _clamp(heater_pre_fc, 0.0, _heater_max_pct)
        if heater_fc_source != "grid":
            _logd.info(f"RoastPlan: pre-FC heater from history {heater_pre_fc:.0f}% "
                       f"[{heater_fc_source}] (n={_h_fc_n})")

        return _BurnerSetpoints(
            heater_dry=heater_dry, heater_maillard=heater_maillard, heater_dev=heater_dev,
            heater_pre_fc=heater_pre_fc, heater_tp=heater_tp,
            heater_source=heater_source, heater_fc_source=heater_fc_source,
            floor=_floor, heater_max_pct=_heater_max_pct, dev_free_pct=_h_dev_free,
            notes=_notes)

    def _resolve_heater_ramp(
            self, *, dry_bt_temperature: float, fc_bt: float,
            maillard_time_min: float, dev_inertia: float,
            expected_tp_bt: float, dry_ror_average: float, to_native,
            heater_dry: float, heater_maillard: float, heater_dev: float,
            heater_pre_fc: float, dev_free_pct: float,
            floor: FloorProfile, heater_max_pct: float,
            heater_resolution_pct: float, has_heater_control: bool,
            heater_de_learned: "float | None", heater_de_samples: int,
            pre_de_descent_samples: int,
            pre_de_lead_learned: "float | None",
            pre_de_step_learned: "float | None",
    ) -> "_HeaterRamp":
        """Anticipated heater ramp geometry (BT-anchored pre-FC anchor, Dev
        Ramp coherence), the learned pre-dry-end anti-flick gesture, and the
        built heater ramp itself (banc 2026-08-05).

        Pure: no history, no ctx object. heater_resolution_pct and
        has_heater_control are read out of ctx at the call site — exactly
        like heater_max_pct in _resolve_burner_setpoints; the learned
        pre-dry-end values are read out of history at the call site. Returns
        the raised pre-FC/dev setpoints, the formatted heater summary, the
        built ramp, the pre-FC BT anchor (still needed by the caller's
        airflow ramp further down), the learned pre-dry-end gesture, and the
        operator notes for the caller to append to history["actions"] —
        exactly like _resolve_burner_setpoints.
        """
        _heater_res: float = heater_resolution_pct
        _has_heater: bool  = has_heater_control
        _floor: FloorProfile = floor
        _heater_max_pct: float = heater_max_pct
        _h_dev_free: float = dev_free_pct

        # ── Anticipated heater ramp (Maillard → Development) ─────────────────
        # The heat reduction that shapes development must land BEFORE first
        # crack, earlier on high-inertia machines. Steps are anchored on BT
        # thresholds (not the clock) so they track the actual roast: one
        # mid-Maillard decrement, then the dev setting applied fc_anticipation
        # seconds ahead of the planned FC. The FC event itself only keeps a
        # guarded fallback (see TilauscopeAlarmFactory).
        fc_anticipation_sec: float = _clamp(20.0 + 70.0 * dev_inertia, 15.0, 90.0)
        # Thresholds computed in °C (fc_bt and dry_bt_temperature are both
        # internal °C now that the plan is °C-internal end to end).
        _dry_c: float = dry_bt_temperature
        _ror_maillard_c: float = ((fc_bt - _dry_c) / maillard_time_min
                                  if maillard_time_min > 0 else 8.0)
        _bt_lead_c: float = max(0.0, _ror_maillard_c) * fc_anticipation_sec / 60.0
        # pre-FC anchor (~1 min avant FC) — défini HORS du bloc heater car l'Air ## TILAU ##
        # Ramp l'utilise aussi ; sinon NameError quand un torréfacteur a l'airflow ## TILAU ##
        # mais pas le contrôle burner (_has_heater False).                          ## TILAU ##
        _pre_fc_c: float = max(_dry_c + 1.0, fc_bt - _bt_lead_c)

        #  Le palier pre-FC appartient encore au MAILLARD : sa valeur de
        # repli est la colonne dev, ce qui posait le feu de DÉVELOPPEMENT une
        # bonne minute avant le FC — le bon réglage au mauvais jalon. Le plancher
        # le borne par le bas. Le plancher COURT DU DRY END AU PALIER PRE-FC, pas
        # au FC : sa fin de courbe (relâchée d'un cran) EST la petite baisse
        # anti-rebond. Au-delà on est dans la transition exothermique, plus sous
        # l'autorité du plancher. La valeur dev n'arrive qu'APRÈS le FC.
        _h_pfc_free = heater_pre_fc
        heater_pre_fc = _clamp(max(heater_pre_fc, _floor.at(1.0)),
                               0.0, _heater_max_pct)
        if heater_pre_fc > _h_pfc_free + 0.5:
            _logd.info(f"RoastPlan: pre-FC heater raised {_h_pfc_free:.0f}→"
                       f"{heater_pre_fc:.0f}% by the bean energy floor")

        # ── Cohérence du résumé de phase avec la Dev Ramp ──────────────────────
        # La Dev Ramp part du palier pre-FC et ne descend jamais de plus de
        # _DEV_BURNER_DROP_CAP (le feu se TIENT en développement). Sans ce
        # recalage, le résumé annonçait un feu dev que la rampe ne suit pas —
        # d'autant plus visible depuis que le plancher relève le palier pre-FC.
        heater_dev = _clamp(max(heater_dev, heater_pre_fc - _DEV_BURNER_DROP_CAP),
                            0.0, _heater_max_pct)
        if heater_dev > _h_dev_free + 0.5:
            _logd.info(f"RoastPlan: development heater raised {_h_dev_free:.0f}→"
                       f"{heater_dev:.0f}% to match the held Dev Ramp")

        heater:str               = [f"{heater_dry:.0f}%", f"{heater_maillard:.0f}%", f"{heater_dev:.0f}%"]

        # ── Geste PRÉVENTIF anti-flick au DRY END — APPRIS, jamais deviné ─────
        # Un flick au DE est un défaut de SETUP propre au grain : réglage de
        # charge un peu trop chaud pour lui. L'opérateur qui l'a déjà vu baisse
        # le feu AVANT la fin du séchage plutôt que de subir la remontée. Ce
        # geste n'appartient donc pas au plan de base — il n'existe que s'il est
        # dans l'historique, et le POURCENTAGE est celui qu'il applique
        # réellement (feu tenu à l'instant du DE, `heater_de_learned`), pas une
        # valeur inventée. Deviner le % ferait apprendre le plan sur lui-même.
        # Même politique d'adoption que partout ailleurs : repli = pas de geste
        # (heater_dry), n=2 blend 50/50, n>=3 la médiane telle quelle. Donc sans
        # historique, aucun geste : le réglage de charge traverse le séchage.
        _hl_de = heater_de_learned
        _h_de_n = int(heater_de_samples or 0)
        if _hl_de is not None and not (0.0 <= float(_hl_de) <= 100.0):
            _hl_de = None
        heater_pre_de, heater_de_source = self._adopt_learned(
            float(heater_dry), float(_hl_de) if _hl_de is not None else None, _h_de_n)
        heater_pre_de = _clamp(heater_pre_de, 0.0, _heater_max_pct)
        # Une baisse plus fine que la résolution machine n'est pas un geste.
        _pre_de_active: bool = heater_pre_de < heater_dry - _heater_res / 2.0
        # Avance et granularité APPRISES du premier geste descendant. La doctrine
        # (30 s) reste le repli quand rien n'est appris : sur la main mesurée le
        # premier geste tombe 90-120 s avant le DRY END, par crans de 1 à 3 %.
        _de_lead_sec: float = _HOLD_LEAD_SEC
        _de_step_pct: float = self._OBSERVABLE_PCT
        _dsc_n = int(pre_de_descent_samples or 0)
        _notes: "list[str]" = []
        if _pre_de_active and _dsc_n >= 2:
            _lead_l = pre_de_lead_learned
            _step_l = pre_de_step_learned
            if _lead_l is not None and 15.0 <= float(_lead_l) <= 300.0:
                _de_lead_sec = float(_lead_l)
            if _step_l is not None and 1.0 <= float(_step_l) <= self._OBSERVABLE_PCT:
                _de_step_pct = float(_step_l)
            _logd.info(f"RoastPlan: learned pre-DRY END descent — starts "
                       f"{_de_lead_sec:.0f}s ahead, steps of {_de_step_pct:.0f}% "
                       f"(n={_dsc_n})")
        if _pre_de_active:
            _logd.info(f"RoastPlan: learned pre-DRY END burner cut "
                       f"{heater_dry:.0f}→{heater_pre_de:.0f}% "
                       f"[{heater_de_source}] (n={_h_de_n})")
            _notes.append(QApplication.translate(
                "tilauscope_roast_plan",
                "On your last roasts of this coffee you brought the burner down to {0}% before dry end rather than waiting — the plan schedules that same reduction {1}s ahead of dry end. It heads off the rate-of-rise bump this bean shows there.").format(
                f"{heater_pre_de:.0f}", f"{_HOLD_LEAD_SEC:.0f}"))

        # ── Rampe heater — ESCALIER PROGRESSIF DÈS LE TP (fondamental Tilau) ──── ## TILAU ##
        # Les valeurs de jalon sont des CIBLES atteintes PROGRESSIVEMENT, À PARTIR
        # DU TP : jamais un saut brutal. Construit par _build_heater_ramp_c —
        # helper PARTAGÉ avec le replan pour que le plan vivant garde la forme
        # progressive (le replan TP écrasait l'escalier → « le feu ne bouge plus »).
        heater_ramp: list[dict] = (
            self._build_heater_ramp_c(
                expected_tp_bt, _dry_c, fc_bt, _ror_maillard_c,
                fc_anticipation_sec, _heater_res,
                heater_dry, heater_maillard, heater_pre_fc, to_native,
                heater_max_pct=_heater_max_pct, floor=_floor,
                dry_end_ror_c=dry_ror_average,
                pre_de_pct=(heater_pre_de if _pre_de_active else 0.0),
                pre_de_lead_sec=_de_lead_sec, pre_de_step_pct=_de_step_pct)
            if _has_heater else [])

        return _HeaterRamp(
            heater_pre_fc=heater_pre_fc, heater_dev=heater_dev, heater=heater,
            heater_ramp=heater_ramp, fc_anticipation_sec=fc_anticipation_sec,
            pre_fc_c=_pre_fc_c, heater_pre_de=heater_pre_de,
            pre_de_active=_pre_de_active, de_lead_sec=_de_lead_sec,
            de_step_pct=_de_step_pct, notes=_notes)

    def _resolve_drum_speed(
            self, *, charge_weight: float, density: float,
            batch_optimal_g: float, drum_variable_speed: bool,
            drum_min_setting: float, drum_step_rpm: float,
            drum_min_rpm: float, drum_max_rpm: float,
    ) -> "_DrumSpeed":
        """Drum Speed — UNE valeur de SETUP (item B, Bench-Integration), banc
        2026-08-05.

        Pure: no ctx object — batch_optimal_g/drum_variable_speed/
        drum_min_setting/drum_step_rpm/drum_min_rpm/drum_max_rpm are read
        out of ctx at the call site, exactly like heater_max_pct in
        _resolve_burner_setpoints. Returns the [dry, mai, dev] drum
        percentage list.
        """
        # ── Drum Speed — UNE valeur de SETUP (item B, Bench-Integration) ─────── ## TILAU ##
        # Doctrine Tilau (2026-07-11) : le tambour se choisit À LA CHARGE selon
        # le poids (dominant) et la densité (espace occupé), puis ne bouge plus —
        # chaque geste in-roast réorganise le lit de grains autour de la sonde et
        # aveugle le RoR mesuré 30-45 s. Les anciens deltas par phase (+5 RPM
        # séchage / +2 dev) sont supprimés.
        # Formule recalée sur les ancres mesurées (corpus Cyberroaster) : la
        # fraction de la PLAGE RPM machine suit le ratio charge/charge-nominale —
        # 400 g (ratio 1,0) → 85 % de réglage, 250 g (ratio 0,625) → 70 % — plus
        # un petit terme densité. Générique : chaque machine applique sa propre
        # plage min/max RPM et son arrondi de pas via rpm_to_percent.
        nominal_charge:float = batch_optimal_g
        _drum_variable:bool = drum_variable_speed

        if _drum_variable:
            _dmin  = drum_min_setting
            _dstep = drum_step_rpm
            _dmin_rpm = drum_min_rpm
            _dmax_rpm = drum_max_rpm
            _w_ratio = charge_weight / max(1.0, nominal_charge)
            _frac = 0.625 + (_w_ratio - 1.0) + ((density - 700.0) / 100.0) * 0.06
            _frac = _clamp(_frac, 0.10, 0.95)
            rpm_setup:float = _dmin_rpm + _frac * max(1.0, _dmax_rpm - _dmin_rpm)
            _drum_pct = self._calculate_rpm_percentage(rpm_setup, _dmin, _dstep)
            # trois colonnes IDENTIQUES : le format de la clé de sortie est
            # conservé (zéro cassure aval — PDF, assistant, factory).
            drum_speed_pct: list[str] = [_drum_pct, _drum_pct, _drum_pct]
        else:
            # Fixed-speed drum: emit a single "N/A" marker so downstream
            # consumers (alarm factory, PDF) know drum events should be skipped.
            drum_speed_pct: list[str] = ["--", "--", "--"]
            _logd.debug("RoastPlan: drum speed events suppressed — roaster has no variable-speed drum")

        return _DrumSpeed(drum_speed_pct=drum_speed_pct)

    def _resolve_airflow_extraction(
            self, *, airwave_present: bool,
            airflow_dependency_index: float, humidity: float,
            ambient_humidity: float, inlet_air_mode: str,
            airflow_resolution_pct: float,
            dry_bt_temperature: float, fc_bt: float, pre_fc_c: float,
            drop_bt_temperature: float, to_native,
            heater_pre_fc: float, heater_dev: float,
            has_heater_control: bool, heater_resolution_pct: float,
            dev_trajectory_learned: "dict | None", dev_traj_samples: int,
    ) -> "_AirflowExtraction":
        """Airflow/extraction base values, the shared learned-trajectory
        helper, the Maillard Air Ramp and the Development Ramp (banc
        2026-08-05).

        Pure: no history, no ctx object — inlet_air_mode/
        airflow_resolution_pct are read out of ctx at the call site, exactly
        like heater_max_pct in _resolve_burner_setpoints; dev_trajectory_learned/
        dev_traj_samples are read out of history at the call site. `self` is
        kept only for shared helpers; the AirWave presence is a PARAMETER, not
        instance state: an attribute assigned per call is exactly the ambient
        dependency this refactor removes — the signature must say what the
        stage reads.
        constants already at module level. Returns the formatted airflow/
        extraction/AirWave-mode summaries and the built Air Ramp / Dev Ramp.
        """
        # derive airflow base from roaster's airflow_dependency_index
        # instead of a binary is_fir_nir toggle.
        # Index = 1.0 (fluid bed, pure convection) → minimum air movement,
        # everything is heat-transfer-via-air → low absolute numbers but high priority.
        # Index = 0.45 (cast iron drum, conduction-dominant) → can tolerate more air.
        # We interpolate between two anchor sets:
        #   low-dep  (0.45) : [28, 42, 60] / [35, 52, 70]
        #   high-dep (1.00) : [15, 22, 32] / [22, 32, 42]
        _adi = airflow_dependency_index  # shorthand

        def _interp_base(low_val: float, high_val: float) -> float:
            # _adi=0.45 → low_val, _adi=1.0 → high_val
            t = _clamp((_adi - 0.45) / (1.00 - 0.45), 0.0, 1.0)
            return low_val + (high_val - low_val) * t

        airflow_base = [
            round(_interp_base(28, 15)),
            round(_interp_base(42, 22)),
            round(_interp_base(60, 32)),
        ]
        extraction_base = [
            round(_interp_base(35, 22)),
            round(_interp_base(52, 32)),
            round(_interp_base(70, 42)),
        ]

        airflow_compensation_percentage:float    = 3.0 if humidity > 11.0 or humidity < 9.0 else 0.0
        extraction_compensation_percentage:float = 5.0 if humidity > 11.0 else (3 if humidity < 9.0 else 0.0)
        extraction_compensation_percentage += 3.0      if ambient_humidity > 70.0 else 0.0

        AIRFLOW_MIN = 20.0
        EXTRACTION_MIN = 30.0
        _airflow_step: float = airflow_resolution_pct # use roaster adjustement steps else set to 5% per default
        airflow_targets = [
            airflow_base[0] + airflow_compensation_percentage,
            airflow_base[1] + airflow_compensation_percentage,
            airflow_base[2] + airflow_compensation_percentage,
        ]
        # Pull machines (rear suction near the exhaust) strip heat as airflow rises;
        # bias the heat-critical DRY phase lower, scaled by airflow dependency.
        if inlet_air_mode == "pull":
            airflow_targets[0] -= round(_adi * 6.0)
        extraction_targets_base = [
            extraction_base[0],
            extraction_base[1],
            extraction_base[2],
        ]

        def finalize_value(val: float, minimum: float) -> float:
            # Clamp to hardware limits and round to resolution step
            clamped = _clamp(val, minimum, 100.0)
            return round(round(clamped / _airflow_step) * _airflow_step)

        # We define the minimum required extraction to maintain the pressure delta
        # DRY: ~1.42x Airflow (Ratio 0.7)
        # MAI: ~1.25x Airflow (Ratio 0.8)
        # DEV: ~1.17x Airflow (Ratio 0.85)
        ratios = [0.70, 0.80, 0.85]

        extraction_targets = []
        for i, air_val in enumerate(airflow_targets):
            ratio_min_extraction = air_val / ratios[i]
            target = max(extraction_targets_base[i], ratio_min_extraction) + extraction_compensation_percentage
            extraction_targets.append(target)

        # Final Processing (Clamping, Rounding, and Formatting)
        airflow = []
        extraction = []
        for i in range(3):
            # Apply final hardware constraints
            air = finalize_value(airflow_targets[i], AIRFLOW_MIN)
            ext = finalize_value(extraction_targets[i], EXTRACTION_MIN)
            # Final safety check: extraction must always be >= airflow
            if ext < air:
                ext = finalize_value(air + _airflow_step, EXTRACTION_MIN)
            airflow.append(f"{air:.0f}%")
            extraction.append(f"{ext:.0f}%")

        # AirWave (extraction) recommendation — kept OUT of the thermal calculation.
        # Detected -> constant low fan (~30/30/35) with a per-phase MODE (FAN/STD/EXT).
        # Absent   -> no extraction recommendation at all.
        if airwave_present:
            extraction   = ["30%", "30%", "35%"]
            airwave_mode = ["FAN", "STD", "EXT"]
        else:
            extraction   = []
            airwave_mode = []

        # ── Trajectoire apprise partagée + helper (Air Ramp & Dev Ramp) ──────── ## TILAU ##
        _dev_traj = dev_trajectory_learned or {}
        _dev_traj_n = int(dev_traj_samples or 0)
        _dev_use_learned = _dev_traj_n >= 2
        _DEV_EXT_RISE_CAP = 10.0   # AirWave puissant : montée douce (≤ +10 vs Maillard)
        def _mai_pct(lst: "list", i: int) -> "float | None":
            try: return float(str(lst[i]).rstrip('%'))
            except (IndexError, ValueError, TypeError): return None

        # ── Rampe AIRFLOW de MAILLARD — montée PROGRESSIVE dès mi-Maillard ────── ## TILAU ##
        # L'airflow chasse les fumées qui arrivent avec le BRUNISSEMENT (mi-
        # Maillard) : on l'ouvre doucement de mi-Maillard au FC (~40 % de la montée
        # totale, pas de 5 %), puis PLUS INTENSÉMENT en DEV (le reste, via la Dev
        # Ramp) pour soutenir la réaction en baissant le feu. « De jalon en jalon,
        # progressivement » (fondamental Tilau). Clé séparée → impact nul alarmes.
        _air_mai = _mai_pct(airflow, 1)
        _air_lrn = _dev_traj.get(0, {}).get(0.75) if _dev_use_learned else None
        _air_dev = _air_lrn if _air_lrn is not None else _mai_pct(airflow, 2)
        _air_fc = _air_mai
        air_ramp: list[dict] = []
        if (_air_mai is not None and _air_dev is not None
                and _air_dev > _air_mai + _airflow_step / 2.0):
            _air_fc = round((_air_mai + (_air_dev - _air_mai) * 0.4) / _airflow_step) * _airflow_step
            _mid_mai_c = _mean(dry_bt_temperature, fc_bt)   # mi-Maillard : arrivée du brunissement
            _a0 = round(_air_mai / _airflow_step) * _airflow_step
            _levels = int(round(max(0.0, _air_fc - _a0) / _airflow_step))
            _rise = max(1e-6, _air_fc - _a0)
            for _k in range(1, _levels + 1):
                _v = _a0 + _airflow_step * _k
                # BT où la montée linéaire atteint le seuil d'arrondi (v − pas/2) :
                # place le palier à SA place réelle (dès mi-Maillard), pas en fin.
                _frac = _clamp((_v - _airflow_step / 2.0 - _a0) / _rise, 0.0, 1.0)
                _bt_a = _mid_mai_c + (pre_fc_c - _mid_mai_c) * _frac
                # _af = fraction mi-Maillard→pre-FC de CE palier, conservée pour  ## TILAU ##
                # que le replan re-cale les seuils à LEUR place réelle (comme le  ## TILAU ##
                # Dev Ramp avec _f), pas en répartition uniforme.                 ## TILAU ##
                air_ramp.append({"bt": round(to_native(_bt_a), 1),
                                 "_af": round(_frac, 4),
                                 "airflow": int(_clamp(_v, AIRFLOW_MIN, 100.0))})

        # ── Rampe de DÉVELOPPEMENT (Dev Ramp) — ESCALIER FIN, feu ↓ / air ↑ ───── ## TILAU ##
        # Prolonge les rampes Maillard EN CONTINUITÉ : heater part de sa valeur
        # PRE-FC (heater_dev, sinon remontée brutale au FC), airflow part de sa
        # valeur AU FC (_air_fc, la Maillard Air Ramp s'y arrête) et monte plus
        # intensément vers la cible dev. Pas d'UNE résolution, seuils rapprochés,
        # cible apprise (f=0.75) si historique ≥ 2 sinon colonne DEV.
        # ## TILAU ## item C : le dev part de la valeur pre-FC RÉELLE de la rampe
        # (feu au FC appris) — continuité au FC préservée quand h_fc ≠ h_dev.
        _dev_start = {3: (float(heater_pre_fc) if has_heater_control else None),
                      0: _air_fc,
                      2: (30.0 if airwave_present else None)}
        _dev_end: dict = {}
        for _et, _col in ((3, float(heater_dev) if has_heater_control else None),
                          (0, _mai_pct(airflow, 2)),
                          (2, 35.0 if airwave_present else None)):
            if _dev_start[_et] is None or _col is None:
                continue
            _lrn = _dev_traj.get(_et, {}).get(0.75) if _dev_use_learned else None
            _tgt = _lrn if _lrn is not None else _col
            if _et == 2:   # extraction : plafond de montée depuis Maillard
                _tgt = min(_tgt, _dev_start[2] + _DEV_EXT_RISE_CAP)
            _dev_end[_et] = _tgt
        # ── TENIR LE FEU en dev (spec AutoPilot §3sexies, banc 2026-07-11) ────── ## TILAU ##
        # Les roasts SMOOTH tiennent le brûleur (~48→42, −6 sur tout le dev) ; la
        # descente profonde (~20-25) est RÉFUTÉE au banc (elle crashe PLUS :
        # 3→6/7 V-crashes en contrefactuel). Plafond de profondeur : la cible
        # apprise (médiane smooth+crashy confondus, souvent −10) se fait clipper
        # — c'est voulu. Le RYTHME (≤5 %/min en fenêtre exotherme) est tenu à
        # l'exécution (_ap_dev_heater_dispense, roast_asssistant).
        # _DEV_BURNER_DROP_CAP est défini plus haut : le résumé de phase s'y cale
        # aussi, pour ne pas annoncer un feu dev que cette rampe ne suivra pas.
        if 3 in _dev_end:
            _dev_end[3] = max(_dev_end[3], _dev_start[3] - _DEV_BURNER_DROP_CAP)
        # ── Airflow SOUTIENT la réaction pendant que le FEU DESCEND en dev ────── ## TILAU ##
        # (doctrine Tilau). Une cible statique `air_dev` — souvent basse ou apprise
        # à plat — laissait le dev quasi plat alors que le brûleur chute franchement.
        # PLANCHER compensatoire : plus le feu perd de %, plus l'air s'ouvre pour
        # soutenir. Non destructif (max) : si l'appris/base ouvre déjà davantage on
        # garde le plus grand. Borné (montée douce, plafonnée) — l'air soutient, le
        # seul frein reste l'AirWave > 30 %. K/plafond deviendront per-roaster (v2).
        _AIR_DEV_SUPPORT_K = 0.6        # +0,6 % d'air par % de feu perdu en dev
        _AIR_DEV_SUPPORT_CAP = 4.0 * _airflow_step   # ≤ +20 % vs la valeur au FC
        if 3 in _dev_end and 0 in _dev_end:
            _burner_drop = max(0.0, _dev_start[3] - _dev_end[3])   # % de feu perdu en dev
            _air_support = _air_fc + min(_AIR_DEV_SUPPORT_K * _burner_drop, _AIR_DEV_SUPPORT_CAP)
            _dev_end[0] = _clamp(_air_support, _dev_end[0], 100.0)
        _dev_res = {3: max(1.0, heater_resolution_pct), 0: _airflow_step, 2: _airflow_step}
        _dev_lohi = {3: (0.0, 100.0), 0: (AIRFLOW_MIN, 100.0), 2: (EXTRACTION_MIN, 100.0)}
        _dev_keys = {3: "heater", 0: "airflow", 2: "extraction"}
        # nb de paliers = plus grand mouvement / résolution (borné 3..8) → ~5 % / pas
        _max_move = max((abs(_dev_end[e] - _dev_start[e]) / _dev_res[e]
                         for e in _dev_end), default=0.0)
        _dev_n = int(_clamp(round(_max_move), 3, 8))
        _dev_ramp = []
        _dev_prev = {e: _dev_start[e] for e in _dev_end}
        for _i in range(1, _dev_n + 1):
            _f = _i / _dev_n
            # seuils répartis de FC jusqu'à ~3° sous le drop (dernier pas avant cooling)
            _bt_f_c = fc_bt + (drop_bt_temperature - 3.0 - fc_bt) * _f
            _entry = {"bt": round(to_native(_bt_f_c), 1), "_f": round(_f, 4)}
            for _et in _dev_end:
                _lo, _hi = _dev_lohi[_et]; _step = _dev_res[_et]
                _desired = _dev_start[_et] + (_dev_end[_et] - _dev_start[_et]) * _f
                _q = _clamp(round(_desired / _step) * _step, _lo, _hi)
                if abs(_q - _dev_prev[_et]) >= _step - 1e-6:   # a bougé d'au moins 1 pas
                    _entry[_dev_keys[_et]] = int(_q)
                    _dev_prev[_et] = _q
            if len(_entry) > 2:   # bt + _f + au moins un levier
                _dev_ramp.append(_entry)
        _dev_ramp_source = (f"learned (n={_dev_traj_n})" if _dev_use_learned else "default")

        return _AirflowExtraction(
            airflow=airflow, extraction=extraction, airwave_mode=airwave_mode,
            air_ramp=air_ramp, dev_ramp=_dev_ramp, dev_ramp_source=_dev_ramp_source)

    def generate_bt_curve_waypoints(
            self,
            charge_temperature: float,
            dry_temperature:    float,
            fc_temperature:     float,
            drop_temperature:   float,
            dry_time_min:    float,   # minutes
            fc_time_min:     float,   # minutes (= dry_time_min + maillard_time_min)
            drop_time_min:   float,   # minutes
            charge_weight: float,
            ror_maillard:  float,
            ror_dev_avg:   float,
            drop_ror:   float,
            expected_tp_bt: float = 100.0,  # machine-specific TP BT (°C); from RoasterContext
        ) -> dict:
            """
            Generates a smooth planned BT curve using piecewise Monotone Cubic (PCHIP)
            interpolation anchored on 6 physiologically meaningful control points:
    
                0. Charge      (t=0,       BT=charge_temperature)
                1. TP          (t≈1.0 min, BT estimated from charge weight + charge temp)
                2. Dry End     (t=dry_time_min,   BT=dry_temperature)
                3. First Crack (t=fc_time_min,    BT=fc_temperature)
                4. Pre-Drop    (t=drop_time_min - 0.5 min, BT interpolated from ROR deceleration)
                5. Drop        (t=drop_time_min,  BT=drop_temperature)
    
            PCHIP is used instead of cubic spline because it preserves monotonicity
            between anchors — it will never overshoot or produce phantom dips
            between the Dry End and First Crack inflection (a known problem with
            natural cubic splines on roast data).
    
            Returns a dict with:
                "time_min"       : list[float]  – time in minutes at 1-second resolution
                "bt_plan"        : list[float]  – planned BT in °C at each time step
                "ror_plan"       : list[float]  – derivative (ROR °C/min) at each time step
                "waypoints"      : list[dict]   – the 6 named anchor points for annotation
            """
            # --- 1. Estimate Turning Point ---
            # Machine-specific TP BT from parameter (passed by generate_roast_plan via RoasterContext).
            # Drum gas: ~100°C  |  Radiant IR (Skywalker): ~95°C (measured median on 83 roasts).
            # °C-PURE: this function works entirely in °C. generate_roast_plan
            # converts the returned grids/waypoints to °F at its output boundary.
            expected_tp = expected_tp_bt
            tp_dip = charge_temperature - expected_tp

            # Adjust dip based on thermal mass (charge weight)
            # Heavier loads = lower TP (larger dip); lighter loads = higher TP (smaller dip)
            # Scale factor normalised to the roaster's nominal batch weight so the
            # adjustment is zero at the machine's intended operating point.
            _ref_weight = ( self._roaster_ctx.nominal_weight_g if hasattr(self._roaster_ctx, '_nominal_weight_g_cache')
                           else 500.0)
            weight_adjustment = (charge_weight - _ref_weight) * 0.005
            tp_dip += weight_adjustment

            # Safety bounds: allow a much larger dip (up to 60% of charge temp)
            min_dip = charge_temperature * 0.3
            max_dip = charge_temperature * 0.6
            tp_dip = _clamp(tp_dip, min_dip, max_dip)

            tp_temperature = charge_temperature - tp_dip
            # TP time: heavier loads take longer to recover; light roast charge temps
            # are lower so thermal exchange is slower → TP arrives later.
            # Model: tp_temperature ≈ 0.9 + charge_weight / 1500  (minutes), bounded [0.75, 1.5]
            tp_time = 0.9 + charge_weight / 1500.0
            tp_time = _clamp(tp_time, 0.75, 1.5)
    
            # --- 2. Pre-Drop anchor ---
            # ROR during development decelerates from ror_dev_avg to drop_ror.
            # Place a pre-drop anchor 0.5 min before drop to capture the deceleration
            # slope — without this, PCHIP draws a straight line into the drop
            # (no deceleration curve visible in the PDF graph).
            t_pre_drop = drop_time_min - 0.5
            # BT at pre-drop: work backward from drop_time_min using the mean of the
            # decelerating ROR segment (average of ror_dev_avg and drop_ror).
            ror_pre_drop_mean = _mean(ror_dev_avg, drop_ror)
            T_pre_drop = drop_temperature - ror_pre_drop_mean * 0.5  # 0.5 min × avg ROR
    
            # --- 3. Named waypoints (used for annotation in the PDF) ---
            # "key" is the STABLE machine identifier (labels are translated,
            # positions can shift if a waypoint is ever inserted) — consumers
            # must look waypoints up by key, not by index or label.
            waypoints = [
                {"key": "charge",   "label": QApplication.translate("Button", "CHARGE"),      "time_min": 0.0,          "bt": round(charge_temperature,    1)},
                {"key": "tp",       "label": QApplication.translate("Label", "TP"),          "time_min": round(tp_time,2), "bt": round(tp_temperature,        1)},
                {"key": "dry_end",  "label": QApplication.translate("Button", "DRY END"),     "time_min": round(dry_time_min,2),"bt": round(dry_temperature,       1)},
                {"key": "fc_start", "label": QApplication.translate("Button", "FC START"),          "time_min": round(fc_time_min, 2),"bt": round(fc_temperature,        1)},
                {"key": "pre_drop", "label": QApplication.translate("Label", "Pre-Drop"),    "time_min": round(t_pre_drop, 2), "bt": round(T_pre_drop, 1)},
                {"key": "drop",     "label": QApplication.translate("Button", "DROP"),        "time_min": round(drop_time_min,2),"bt": round(drop_temperature,     1)},
            ]
    
            # --- 4. Build the PCHIP grids from the anchors (shared builder) ---
            return self._build_pchip_curve(waypoints)

    def generate_roast_plan(self, bean:GreenBean, agtron_target:AgtronScale, ambient_temp:float, ambient_humidity:float, charge_weight:float, roast_altitude:float, bt_deviation:ProbeDeviation|None, airwave_present:bool=False, minutes_since_last_drop:'float | None'=None):
        
        # ── UNIT NORMALISATION ───────────────────────────────────────────────────
        # All internal physics maths are in °C.
        # If Artisan is running in °F the caller passes °F values; convert them
        # to °C here so every formula below is unit-safe.
        # We convert back to the native unit only in the final output dict.
        from artisanlib.util import fromFtoCstrict, fromCtoFstrict

        _is_fahrenheit = (self.mode == "F")

        def _to_c(val: float) -> float:
            """Convert a value from the current Artisan unit to °C."""
            return fromFtoCstrict(val) if _is_fahrenheit else val

        def _to_native(val_c: float) -> float:
            """Convert an internal °C value back to the Artisan display unit."""
            return fromCtoFstrict(val_c) if _is_fahrenheit else val_c
        
        # Normalise the two incoming temperature arguments that are unit-dependent.
        # ambient_temp is only echoed in the output; normalise it for consistency.
        ambient_temp_c = _to_c(ambient_temp)   # used for output echo only
        # (charge_weight, roast_altitude, ambient_humidity are unit-independent)
        # ── END UNIT NORMALISATION ───────────────────────────────────────────────
        
        # AirWave detected at plan time? Gates the AirWave (extraction) reco; the
        # AirWave stays OUT of the thermal calculation either way.
        self._airwave_present: bool = bool(airwave_present)

        # --- 0. Variable Extraction & General Constants ---
        density = bean.density
        humidity = bean.last_humidity
        process_type = bean.process or ""
        culture_altitude = bean.altitude
        process_type_lower = process_type.lower()

        # ── Roaster context shortcuts ──────────────────────────────────────────
        # All machine-specific constants come from RoasterContext when available.
        ctx = self._roaster_ctx  # may be None → use generic defaults below

        # Local flag — do NOT store on RoasterContext to avoid structural change.
        # True for FIR/NIR radiant electric machines (Skywalker, Kaleido, Cyberroaster).
        is_electric_radiant: bool = ctx.is_radiant_electric if ctx is not None else False
        # Keep legacy alias used by downstream blocks (light-roast FIR correction)
        is_fir_nir: bool = is_electric_radiant

        # Point 2: clamp charge weight to roaster's valid batch range
        charge_weight = self._clamp_batch_weight(charge_weight)

        # Point 4 & 5: thermal indices from roaster profile
        # Defaults are mid-range typical drum values when no context is loaded.
        _thermal_mass_idx       = ctx.thermal_mass_index       if ctx else 0.65
        _heat_retention_idx     = ctx.heat_retention_index     if ctx else 0.65
        _airflow_dep_idx        = ctx.airflow_dependency_index if ctx else 0.65
        _thermal_response_speed = ctx.thermal_response_speed   if ctx else 0.70

        # Dev thermal inertia: scales drop_temp within [min, max] range.
        # Scale: 0.0 = ideal instant-cut machine, 1.0 = multi-kg shop cast-iron
        # drum (headroom — the current fleet tops out at 0.7, Santoker/Hottop).
        # Blends stored-mass momentum AND actuator lag (see roasters.json notes).
        # Default 0.8 = conventional shop gas drum (no-context fallback only).
        _dev_inertia: float = (
            ctx.dev_thermal_inertia_factor if ctx is not None else 0.8
        )

        # Expected TP BT in °C — machine-specific.
        # Drum gas: ~100°C  |  Radiant IR (SW): ~95°C
        _expected_tp_bt: float = (
            ctx.expected_tp_bt if ctx is not None else 100.0
        )

        # Nominal batch weight for thermal-mass maths
        # Point 2: use roaster's optimal capacity instead of hardcoded 500 g
        _nominal_weight_g: float = ctx.nominal_weight_g if ctx else 500.0
        _optimal_batch_g: float = ctx.batch_optimal_g if ctx else 500.0

        # Build a default bt_deviation whenever the caller passed none — works
        # with OR without a RoasterContext (ctx can be None when the roaster
        # name does not resolve in the registry; we must not crash downstream
        # in _adjust_deviation, which dereferences bt_deviation.bt_at_charge).
        if bt_deviation is None:
            from tilauscope.tilauscope_types import ProbeDeviationInterval
            off = getattr(ctx, "bt_offsets", None) if ctx is not None else None
            if off and len(off) >= 4:
                bt_deviation = ProbeDeviation(
                    probe_id        = "",
                    bt_at_charge    = ProbeDeviationInterval(off[0], off[0]),
                    bt_at_de        = ProbeDeviationInterval(off[1], off[1]),
                    bt_at_fc        = ProbeDeviationInterval(off[2], off[2]),
                    bt_at_drop      = ProbeDeviationInterval(off[3], off[3]),
                )
                _logd.debug(f"RoastPlan: using roaster stored BT offsets {off}")
            else:
                bt_deviation = ProbeDeviation(
                    probe_id        = "",
                    bt_at_charge    = ProbeDeviationInterval(0.0, 0.0),
                    bt_at_de        = ProbeDeviationInterval(0.0, 0.0),
                    bt_at_fc        = ProbeDeviationInterval(0.0, 0.0),
                    bt_at_drop      = ProbeDeviationInterval(0.0, 0.0),
                )
                _logd.warning(
                    "RoastPlan: no roaster context/offsets — zero BT deviation"
                )
        # Cache thermal_response_speed so _analyze_historical_roasts can
        # use it for debounce scaling without re-importing ctx there.
        self._thermal_response_speed_cache = _thermal_response_speed

        # ── Historical analysis — run EARLY so the learned FC temperature can
        # feed the whole plan (Maillard delta, heater ramp, PCHIP curve, dev
        # slope). Also provides the master curve / crash / flick data consumed
        # in the output section below. Memoised: ambient-triggered plan
        # regenerations reuse the cached analysis (same bean/target/weight).
        history = self._get_history_cached(bean, agtron_target, charge_weight)

        # DETERMINE TARGET ROAST CATEGORY
        target_roast_category = agtron_target.name

        roasting_basic_base: RoasterBasicPlan = RoasterBasicPlan(
            plans=[
                RoasterBasicPlanPerPhase(
                    name="Very Light",
                    heater_cmfc=(0.85, 0.70, 0.50),
                    charge_temp=(175, 185),
                    total_time=(7.5, 8.75),
                    drying_time=(3.5, 4.0),
                    maillard_time=(3.0, 3.5),
                    development_time=(1.0, 1.25),
                    dtr_pct=(0.13, 0.15),
                    drop_temp=(197, 203),
                    fc_temp=194,
                    dry_temp=153,
                ),
                RoasterBasicPlanPerPhase(
                    name="Light",
                    heater_cmfc=(0.85, 0.70, 0.50),
                    charge_temp=(185, 195),
                    total_time=(8.25, 10.25),
                    drying_time=(3.5, 4.5),
                    maillard_time=(3.5, 4.0),
                    development_time=(1.25, 1.75),
                    dtr_pct=(0.15, 0.17),
                    drop_temp=(203, 208),
                    fc_temp=195,
                    dry_temp=155,
                ),
                RoasterBasicPlanPerPhase(
                    name="Medium Light",
                    heater_cmfc=(0.75, 0.65, 0.45),
                    charge_temp=(190, 200),
                    total_time=(9.75, 11.25),
                    drying_time=(4.5, 5.0),
                    maillard_time=(3.75, 4.25),
                    development_time=(1.5, 2.0),
                    dtr_pct=(0.17, 0.19),
                    drop_temp=(208, 213),
                    fc_temp=196,
                    dry_temp=158,
                ),
                RoasterBasicPlanPerPhase(
                    name="Medium",
                    heater_cmfc=(0.75, 0.60, 0.45),
                    charge_temp=(195, 205),
                    total_time=(11.0, 12.75),
                    drying_time=(4.75, 5.25),
                    maillard_time=(4.25, 4.75),
                    development_time=(2.0, 2.75),
                    dtr_pct=(0.18, 0.22),
                    drop_temp=(212, 217),
                    fc_temp=198,
                    dry_temp=160,
                ),
                RoasterBasicPlanPerPhase(
                    name="Medium Dark",
                    heater_cmfc=(0.70, 0.60, 0.40),
                    charge_temp=(200, 210),
                    total_time=(12.25, 14.0),
                    drying_time=(5.0, 5.5),
                    maillard_time=(4.5, 5.0),
                    development_time=(2.75, 3.5),
                    dtr_pct=(0.22, 0.25),
                    drop_temp=(217, 222),
                    fc_temp=200,
                    dry_temp=162,
                ),
                RoasterBasicPlanPerPhase(
                    name="Dark",
                    heater_cmfc=(0.70, 0.60, 0.42),
                    charge_temp=(200, 210),
                    total_time=(13.0, 15.0),
                    drying_time=(5.0, 5.5),
                    maillard_time=(4.5, 5.0),
                    development_time=(3.5, 4.5),
                    dtr_pct=(0.27, 0.30),
                    drop_temp=(221, 226),
                    fc_temp=202,
                    dry_temp=163,
                ),
                RoasterBasicPlanPerPhase(
                    name="Very Dark",
                    heater_cmfc=(0.72, 0.62, 0.44),
                    charge_temp=(200, 210),
                    total_time=(14.0, 16.0),
                    drying_time=(5.0, 5.5),
                    maillard_time=(4.5, 5.0),
                    development_time=(4.5, 5.5),
                    dtr_pct=(0.32, 0.34),
                    drop_temp=(224, 229),
                    fc_temp=203,
                    dry_temp=164,
                ),
                RoasterBasicPlanPerPhase(
                    name="Extremely Dark",
                    heater_cmfc=(0.72, 0.62, 0.44),
                    charge_temp=(205, 215),
                    total_time=(14.75, 17.25),
                    drying_time=(5.0, 5.5),
                    maillard_time=(4.75, 5.25),
                    development_time=(5.0, 6.5),
                    dtr_pct=(0.34, 0.38),
                    drop_temp=(228, 236),
                    fc_temp=204,
                    dry_temp=165,
                ),
            ]
        )
        target_roast_category = agtron_target.name # 2026/02/18 fix specific light roast settings for FIR and NIR heaters
        is_light_roast = target_roast_category in ["Light", "Very Light"]
        if is_light_roast and is_fir_nir:
            i = 1 if target_roast_category == "Light" else 0
            # FIR/NIR-specific corrections (radiant heat behaviour only).
            # Development leg lowered to 0.45 so the light ladder stays monotone
            # against the Medium Light grid (which holds 0.45 in development).
            # Charge is no longer set here — the process/BT charge band owns it.
            roasting_basic_base.plans[i].heater_cmfc   = (0.65, 0.60, 0.45)
            roasting_basic_base.plans[i].total_time    = (8.0, 10.5)
            roasting_basic_base.plans[i].drying_time   = (3.5, 5.0)
            roasting_basic_base.plans[i].maillard_time = (3.0, 4.0)
            roasting_basic_base.plans[i].drop_temp     = (201, 203)
            # Development window widened so the DTR-driven dev_time (computed
            # below) is actually reachable instead of being clamped short. The
            # previous caps (dev 0.45-1.0 / dtr 0.10-0.15) forced calculated DTR
            # well under target. Split per-category so Very Light stays brighter
            # and shorter in development than Light.
            if target_roast_category == "Light":
                roasting_basic_base.plans[i].development_time = (1.0, 1.7)
                roasting_basic_base.plans[i].dtr_pct          = (0.14, 0.17)
            else:  # Very Light
                roasting_basic_base.plans[i].development_time = (0.7, 1.4)
                roasting_basic_base.plans[i].dtr_pct          = (0.12, 0.15)
        # first adjust the roasting basic plan based on probe deviations
        roasting_basic:RoasterBasicPlan = self._adjust_deviation(bt_deviation, roasting_basic_base)
        roast_constraints:RoasterBasicPlanPerPhase = next((p for p in roasting_basic.plans if p.name == target_roast_category), None)
        if roast_constraints is None:
            _logd.warning(f"Category {target_roast_category} not found, falling back to Medium.")
            # Fallback to Medium, or the first available plan
            roast_constraints = next((p for p in roasting_basic.plans if p.name == "Medium"), roasting_basic.plans[0])

        # we consider that we sant to acheive regular roasts between 30-80 Ag
        AGTRON_MIN = 30.0
        AGTRON_MAX = 80.0
        # dry end is taken from the plan grid (not hardcoded) — offsets applied below.
        # °C-INTERNAL: like charge/fc/drop, this stays in °C; the single °F
        # conversion happens at the output boundary. (The old early conversion
        # here made every dry-end-derived value mixed-unit in °F mode.)
        dry_end_bt:float = float(roast_constraints.dry_temp)

        # add deviation due to roaster 
        dry_bt_temperature:float =  dry_end_bt + _mean(bt_deviation.bt_at_de.start_min , bt_deviation.bt_at_de.end_min)
        fc_bt_temperature:float  = roast_constraints.fc_temp + _mean(bt_deviation.bt_at_fc.start_min , bt_deviation.bt_at_fc.end_min)  

        # average color target of the plan        
        agtron_mean = _mean(agtron_target.agtron_range.max_value,agtron_target.agtron_range.min_value)
        agtron_norm = _clamp(agtron_mean, AGTRON_MIN, AGTRON_MAX)
        # agtron_ratio: 0.0 = Dark (30), 1.0 = Light (75)
        agtron_ratio = (agtron_norm - AGTRON_MIN) / (AGTRON_MAX - AGTRON_MIN)

        # Cache for use in generate_bt_curve_waypoints
        self._nominal_weight_g_cache = _nominal_weight_g

        # calculate fc temperature — grid chain: grid value + probe deviation
        # (already in fc_bt_temperature) + roast-altitude correction.
        adj_roast_alt:float = (roast_altitude / 300.0)
        _fc_grid:float = fc_bt_temperature - adj_roast_alt

        # Learned FC (per bean × machine) from the historical cohort.
        # Adoption policy (progressive): n>=3 → median adopted as-is;
        # n==2 → 50/50 blend with the grid chain (robust to one mis-marked FC);
        # n<2 or implausible → grid chain.
        # The learned value REPLACES the probe-deviation and altitude
        # corrections: both are already embedded in measurements from this rig.
        _fc_learned = history.get("fc_bt_learned_c") if history else None
        _fc_n:int = int(history.get("fc_bt_samples", 0) or 0) if history else 0

        # Plausibility gate, then the shared progressive-adoption policy.
        if _fc_learned is not None and not (175.0 <= _fc_learned <= 212.0):
            _fc_learned = None
        fc_bt, fc_source = self._adopt_learned(_fc_grid, _fc_learned, _fc_n)

        # ── Charge setup: band by PROCESS, bean/ambient modulation, and
        # inter-batch heat soak — extracted to _charge_setup (banc 2026-08-05),
        # see that method for the doctrine comments. Called here, ahead of the
        # FC regression below, so its pre-modulation band midpoint
        # (nominal_temperature_c) is available for that adjustment, exactly as
        # in the original interleaved order — the regression does not depend
        # on the modulation/soak outcome, and the modulation/soak does not
        # depend on fc_bt, so pulling the whole stage ahead of the regression
        # does not change the result.
        _charge = self._charge_setup(
            process_type_lower=process_type_lower, density=density,
            culture_altitude=culture_altitude, humidity=humidity,
            ambient_temp_c=ambient_temp_c, minutes_since_last_drop=minutes_since_last_drop,
            thermal_mass_idx=_thermal_mass_idx, heat_retention_idx=_heat_retention_idx)
        _charge_band = _charge.band
        _charge_temperature = _charge.nominal_temperature_c

        # ## TILAU ## FC regression adjustment by charge temperature
        # If learned FC has regression coefficients, adjust it based on planned charge.
        _fc_regression_slope = history.get("fc_regression_slope") if history else None
        _fc_regression_offset = history.get("fc_regression_offset") if history else None
        if fc_source == "learned" and _fc_regression_slope is not None and _fc_regression_offset is not None:
            fc_bt_adjusted = round(_fc_regression_slope * _charge_temperature + _fc_regression_offset, 1)
            _logd.info(f"RoastPlan: FC regression adjustment: charge {_charge_temperature:.1f}°C "
                       f"→ FC {fc_bt:.1f}°C → {fc_bt_adjusted}°C (slope={_fc_regression_slope:.4f})")
            fc_bt = fc_bt_adjusted
        elif fc_source != "grid":
            _logd.info(
                f"RoastPlan: FC from history {fc_bt:.1f}°C [{fc_source}] "
                f"(grid chain was {_fc_grid:.1f}°C)")

        # calculate delta temp (e.g. maillard) diff between adjusted FC and DRY END
        ma_bt_temperature = fc_bt - dry_bt_temperature

        charge_bt_temperature: float = _charge.temperature_c
        _soak_dcharge_c: float = _charge.soak_dcharge_c
        _soak_dheater: int = _charge.soak_dheater_pct

        # RoR scale for the OUTPUT BOUNDARY only — all internal RoR maths stay
        # in °C/min; displayed/exported RoR values are scaled once at the end.
        _ror_scale:float = 1.8 if _is_fahrenheit else 1.0  # °F/min = °C/min × 1.8

        # Expected RoR bands (industry reference, °C/min). These are NOT displayed
        # and do NOT shape the curve — they only serve as validation/fallback bounds.
        # The geometry (grid temps/times) is the single source of truth; the
        # actual maillard/dev RoR are derived from it below.
        ror_maillard_expected = 8.0 + (16.0 - 8.0) * agtron_ratio
        dev_ror_expected      = 4.0 + (6.0 - 4.0) * agtron_ratio

        # DTR is no longer a target here (owner ruling 2026-08-04): development
        # duration is set below from the professional absolute-time band, and
        # the ratio is only ever REPORTED as a consequence — see dtr_achieved
        # further down. roast_constraints.dtr_pct is kept as a reference window
        # for that sanity check only, never as a driver.

        # ── Phase timings anchored on TOTAL (owner ruling 2026-08-04) ───────
        # Base durations extracted to _base_phase_durations (banc 2026-08-05) —
        # see that method for the doctrine comments on the split.
        total_time_min, dry_time_min, dev_time_min = self._base_phase_durations(
            roast_constraints=roast_constraints, density=density, humidity=humidity)

        heater_dry_base:float = roast_constraints.heater_cmfc[0]*100 # create variable to compute heater requirement for dry phase
        airflow_compensation_percentage:float = 0.0
        extraction_compensation_percentage:float = 0.0

        # --- Water Activity Adjustment (from GreenBean.water_activity) ---
        effect = self._water_activity_effect(bean.water_activity)
        dry_time_min += effect.d_dry_time_min
        heater_dry_base += effect.d_heater_dry_pct
        airflow_compensation_percentage += effect.d_airflow_pct
        extraction_compensation_percentage += effect.d_extraction_pct
        charge_bt_temperature += effect.d_charge_c
        if effect.d_dry_time_min < 0.0:
            # Floor 5 points below the nominal share, not at it: flooring on
            # _DRY_SHARE exactly would cancel the very shortening this branch
            # exists to apply. "About half the roast" tolerates that margin.
            dry_time_min = max(total_time_min * (_DRY_SHARE - 0.05), dry_time_min)
        if effect.d_charge_c < 0.0:
            # Floored on the PROCESS band, not the Agtron grid: since 2026-08-04
            # the charge no longer comes from roast_constraints.charge_temp, and
            # flooring there could push the charge outside its own process band.
            charge_bt_temperature = max(_charge_band[0], charge_bt_temperature)

        # ── Cross-roast timing calibration + physical duration floors ───────
        # Extracted to _calibrate_and_floor_phase_durations (banc 2026-08-05) —
        # see that method for the calibration and floor doctrine comments, and
        # for why the floors must run after the calibration.
        _timing = self._calibrate_and_floor_phase_durations(
            dry_time_min=dry_time_min, total_time_min=total_time_min, dev_time_min=dev_time_min,
            drying_time_band=roast_constraints.drying_time,
            maillard_time_band=roast_constraints.maillard_time,
            t_dry_raw=history.get("timing_dry_min_learned") if history else None,
            t_fc_raw=history.get("timing_fc_min_learned") if history else None,
            t_n=int(history.get("timing_samples", 0) or 0) if history else 0)
        dry_time_min      = _timing.dry_time_min
        maillard_time_min = _timing.maillard_time_min
        timing_source      = _timing.timing_source
        _cal_heater_dry    = _timing.cal_heater_dry_pct
        _cal_heater_mai    = _timing.cal_heater_mai_pct
        if _timing.notes and history is not None:
            history["actions"] = (history.get("actions") or []) + _timing.notes

        # determine DRY RoR peak (°C/min — scaled at the output boundary)
        dry_ror_peak:float = 12.0 if not is_fir_nir else heater_dry_base / 75.0 * 12.0
        # Real post-TP dry-phase RoR: rise from the turning point to dry-end over
        # the active drying time. The old (charge - dry_end)/dry_time ignored the
        # post-charge dip and was not the drying RoR at all. Uses the machine TP
        # (expected_tp_bt) and the planned TP time (same model as the BT curve).
        _tp_time_min: float  = max(0.75, min(1.5, 0.9 + charge_weight / 1500.0))
        _dry_active_min: float = max(0.5, dry_time_min - _tp_time_min)
        dry_ror_average: float = (dry_bt_temperature - _expected_tp_bt) / _dry_active_min
        # Align the dry RoR target to the CHARGE->DRY band so the plan target stays
        # consistent with the live phase classifier (no "on plan" reading as warn).
        # Band requested in °C — the internal frame; scaled at the output boundary.
        _dry_band_lo, _dry_band_hi = get_ror_ideal_band("drying", "C")
        dry_ror_average = max(_dry_band_lo, min(_dry_band_hi, dry_ror_average))
           
        # maillard_time_min set in the timing-calibration block above
        # (total - dry - dev by deduction, or learned from history when the
        # cohort allows it).
        # GEOMETRY-DERIVED maillard RoR: the real average slope the BT curve will
        # follow between the dry-end and FC anchors. Replaces the old standalone
        # formula that was displayed but never used to build the curve. °C/min
        # (both anchors are internal °C); scaled at the output boundary.
        ror_maillard:float = (ma_bt_temperature / maillard_time_min
                              if maillard_time_min > 0 else ror_maillard_expected)

        # dev_time_min set from the professional development-time band above
        # (absolute duration, owner ruling 2026-08-04 — no longer DTR-derived).

        # Calculate Final Total Time (drop_time_min) and FC Time (before constraints)
        drop_time_min:float = dry_time_min + maillard_time_min + dev_time_min
        # deduct first crack from other values
        fc_time_min:float = dry_time_min + maillard_time_min

        # phase share (%) for display — development share is a byproduct of the
        # retained durations, not a target.
        if drop_time_min > 0:
            dry_phase_percent:float = round((dry_time_min / drop_time_min) * 100.0,0)
            maillard_phase_percent:float = round((maillard_time_min / drop_time_min) * 100.0,0)
            dev_phase_percent:float = 100.0 - dry_phase_percent - maillard_phase_percent
        else:
            dry_phase_percent:float = 0.0
            maillard_phase_percent:float = 0.0
            dev_phase_percent:float = 0.0

        # DTR is the RESULT of the durations above, never their driver (owner
        # ruling 2026-08-04 — same doctrine as the rate of rise: settings are
        # the cause, observables are the consequence). roast_constraints.dtr_pct
        # is a reference window only, used here for a sanity note on the front
        # of the roast (drying + Maillard), not to steer development.
        dtr_achieved: float = (dev_time_min / drop_time_min) if drop_time_min > 0 else 0.0
        if not (roast_constraints.dtr_pct[0] <= dtr_achieved <= roast_constraints.dtr_pct[1]):
            _logd.warning(
                f"RoastPlan: development ratio {dtr_achieved*100:.1f}% falls outside "
                f"the usual window {roast_constraints.dtr_pct[0]*100:.0f}-"
                f"{roast_constraints.dtr_pct[1]*100:.0f}% for this roast level "
                f"(dev={dev_time_min:.2f}min, total={drop_time_min:.2f}min)."
            )
            if history is not None:
                history["actions"] = (history.get("actions") or []) + [QApplication.translate(
                    "tilauscope_roast_plan",
                    "The planned development ratio ({0}%) lands outside the usual window for this roast level ({1}-{2}%) — the roast reaches first crack {3} than the style expects.").format(
                    f"{dtr_achieved*100:.1f}", f"{roast_constraints.dtr_pct[0]*100:.0f}",
                    f"{roast_constraints.dtr_pct[1]*100:.0f}",
                    "later" if dtr_achieved < roast_constraints.dtr_pct[0] else "earlier")]

        # drop_bt_temperature: scale within [drop_min, drop_max] using dev_thermal_inertia_factor.
        # High inertia (shop cast-iron drum, _dev_inertia→1.0) → upper range (keeps climbing);
        # fleet maximum is currently 0.7 (Santoker X3 / Hottop).
        # Fast response (radiant IR / fluid bed, _dev_inertia→0.0) → lower range (can plateau near FC).
        # Additional corrections: agtron offset (darker = higher drop) and thermal mass.
        # Bounded to ±6 °C: the raw term uses the band MIDPOINT, which for the off-scale
        # "Very Light" band (mid 115.5) reached -20 °C — unphysical, and only ever masked
        # by the grid clamp below. The ±6 envelope matches the empirical drop_BT-vs-Agtron
        # slope measured on 144 real roasts (-0.323 °C/Agtron-pt → ~+6 °C at the darkest
        # observed category, Medium Dark), and prevents double-counting against the grid's
        # already-hot dark drop bands at the (un-sampled) dark extreme.
        agtron_offset: float = _clamp(
            (_mean(agtron_target.agtron_range.min_value, agtron_target.agtron_range.max_value) - 65) * -0.4,
            -6.0, 6.0,
        )
        thermal_offset: float = (ctx.thermal_mass_index - 0.5) * -2.0 if ctx and ctx.thermal_mass_index > 0.5 else 0.0
        _drop_min = float(roast_constraints.drop_temp[0])
        _drop_max = float(roast_constraints.drop_temp[1])
        drop_bt_temperature = (
            _drop_min + (_drop_max - _drop_min) * _dev_inertia
            + agtron_offset + thermal_offset
        )
        # clamp to grid bounds after all adjustments
        drop_bt_temperature = _clamp(drop_bt_temperature, _drop_min, _drop_max)

        # ── Learned drop, FC→DROP coherence, and drop/dev RoR — extracted to
        # _resolve_drop_and_dev_ror (banc 2026-08-05), see that method for the
        # doctrine comments (learned-colour adoption, the coherence rebuild,
        # and the RoR floors).
        _drop = self._resolve_drop_and_dev_ror(
            drop_bt_temperature=drop_bt_temperature, drop_min=_drop_min, drop_max=_drop_max,
            drop_learned_c=(history.get("drop_bt_learned_c") if history else None),
            drop_samples=(int(history.get("drop_bt_samples", 0) or 0) if history else 0),
            drop_ror_learned_c=(history.get("drop_ror_learned_c") if history else None),
            drop_ror_samples=(int(history.get("drop_ror_samples", 0) or 0) if history else 0),
            fc_bt=fc_bt, dev_time_min=dev_time_min,
            dev_ror_expected=dev_ror_expected, agtron_ratio=agtron_ratio,
            charge_weight=charge_weight, density=density, water_activity=bean.water_activity,
            nominal_weight_g=_nominal_weight_g, heat_retention=_heat_retention_idx,
            is_fir_nir=is_fir_nir)
        drop_bt_temperature = _drop.drop_bt_temperature
        drop_source = _drop.drop_source
        dev_ror = _drop.dev_ror
        drop_ror = _drop.drop_ror
        drop_ror_source = _drop.drop_ror_source
        if _drop.notes and history is not None:
            history["actions"] = (history.get("actions") or []) + _drop.notes

        # Calculate TP
        # scale the TP dip constant by (1 - thermal_mass_index) so
        # machines with high thermal mass (cast iron, 0.85) produce a smaller
        # initial dip (they hold heat longer), while low-mass machines (fluid
        # bed, 0.15) show a sharper, faster dip.
        _tp_dip_base:float   = 30.0   # °C — internal frame, converted at output
        _tp_dip_const:float  = _tp_dip_base * (1.0 + (0.5 - _thermal_mass_idx))  # 0→+15, 1→-15
        tp_temperature:float = charge_bt_temperature - _tp_dip_const - (charge_weight / 50)
        
        # ── Drum Speed — extracted to _resolve_drum_speed (banc 2026-08-05),
        # see that method for the doctrine comments (SETUP-only value, held
        # for all three phases, per-machine RPM range and step rounding).
        _drum_variable:bool = ctx.drum_variable_speed if ctx is not None else True
        _drum = self._resolve_drum_speed(
            charge_weight=charge_weight, density=density,
            batch_optimal_g=(ctx.batch_optimal_g if ctx else 375.0),
            drum_variable_speed=_drum_variable,
            drum_min_setting=(ctx.drum_min_setting if ctx is not None else 0.0),
            drum_step_rpm=(ctx.drum_step_rpm if ctx is not None else 1.0),
            drum_min_rpm=(ctx.drum_min_rpm if ctx is not None else 34.0),
            drum_max_rpm=(ctx.drum_max_rpm if ctx is not None else 68.0))
        drum_speed_pct: list[str] = _drum.drum_speed_pct

        # Heater ceiling: hardware limit, not a style choice — some elements
        # (e.g. the ITOP Cyberroaster's FIR/NIR emitter) degrade above a
        # machine-specific power fraction, so the upper clamp bound is read
        # from the roaster context instead of a fixed 100.0.
        _heater_max_pct: float = ctx.heater_max_pct if ctx is not None else 100.0

        # ── Burner setpoints (grid/learned dry/Maillard/dev/pre-FC, Maillard
        # energy floor) — extracted to _resolve_burner_setpoints (banc
        # 2026-08-05), see that method for the doctrine comments (process/
        # humidity grid base, learned heater profile adoption policy, the
        # Maillard energy floor, and the learned pre-FC setpoint).
        _burner = self._resolve_burner_setpoints(
            humidity=humidity, ambient_humidity=ambient_humidity,
            is_light_roast=is_light_roast, is_fir_nir=is_fir_nir,
            agtron_mean=agtron_mean, process_type_lower=process_type_lower,
            process_type=process_type, density=density,
            bean_varieties=bean.varieties or "", bean_country=bean.country or "",
            water_activity=bean.water_activity, ambient_temp_c=ambient_temp_c,
            roast_constraints=roast_constraints,
            cal_heater_dry_pct=_cal_heater_dry, cal_heater_mai_pct=_cal_heater_mai,
            soak_dheater_pct=_soak_dheater, heater_max_pct=_heater_max_pct,
            heater_samples=(int(history.get("heater_samples", 0) or 0) if history else 0),
            heater_dry_learned=(history.get("heater_dry_learned") if history else None),
            heater_mai_learned=(history.get("heater_mai_learned") if history else None),
            heater_dev_learned=(history.get("heater_dev_learned") if history else None),
            heater_fc_learned=(history.get("heater_fc_learned") if history else None),
            heater_fc_samples=(int(history.get("heater_fc_samples", 0) or 0) if history else 0))
        heater_dry = _burner.heater_dry
        heater_maillard = _burner.heater_maillard
        heater_dev = _burner.heater_dev
        heater_pre_fc = _burner.heater_pre_fc
        heater_tp = _burner.heater_tp
        heater_source = _burner.heater_source
        heater_fc_source = _burner.heater_fc_source
        _floor = _burner.floor
        _heater_max_pct = _burner.heater_max_pct
        _h_dev_free = _burner.dev_free_pct
        if _burner.notes and history is not None:
            history["actions"] = (history.get("actions") or []) + _burner.notes

        # ── Anticipated heater ramp (BT-anchored pre-FC anchor, Dev Ramp
        # coherence), learned pre-dry-end anti-flick gesture, and the built
        # heater ramp — extracted to _resolve_heater_ramp (banc 2026-08-05),
        # see that method for the doctrine comments (why the pre-FC anchor
        # is defined outside the heater-only block, the Maillard-floor
        # coherence with the Dev Ramp, and the learned pre-dry-end descent
        # policy).
        _heater_res: float = ctx.heater_resolution_pct if ctx is not None else 1.0
        _has_heater: bool  = bool(ctx.has_heater_control) if ctx is not None else True
        _ramp = self._resolve_heater_ramp(
            dry_bt_temperature=dry_bt_temperature, fc_bt=fc_bt,
            maillard_time_min=maillard_time_min, dev_inertia=_dev_inertia,
            expected_tp_bt=_expected_tp_bt, dry_ror_average=dry_ror_average,
            to_native=_to_native,
            heater_dry=heater_dry, heater_maillard=heater_maillard, heater_dev=heater_dev,
            heater_pre_fc=heater_pre_fc, dev_free_pct=_h_dev_free,
            floor=_floor, heater_max_pct=_heater_max_pct,
            heater_resolution_pct=_heater_res, has_heater_control=_has_heater,
            heater_de_learned=(history.get("heater_de_learned") if history else None),
            heater_de_samples=(int(history.get("heater_de_samples", 0) or 0) if history else 0),
            pre_de_descent_samples=(int(history.get("pre_de_descent_samples", 0) or 0) if history else 0),
            pre_de_lead_learned=(history.get("pre_de_lead_learned") if history else None),
            pre_de_step_learned=(history.get("pre_de_step_learned") if history else None))
        heater_pre_fc = _ramp.heater_pre_fc
        heater_dev = _ramp.heater_dev
        heater = _ramp.heater
        heater_ramp = _ramp.heater_ramp
        fc_anticipation_sec = _ramp.fc_anticipation_sec
        _pre_fc_c = _ramp.pre_fc_c
        heater_pre_de = _ramp.heater_pre_de
        _pre_de_active = _ramp.pre_de_active
        _de_lead_sec = _ramp.de_lead_sec
        _de_step_pct = _ramp.de_step_pct
        if _ramp.notes and history is not None:
            history["actions"] = (history.get("actions") or []) + _ramp.notes

        # ── Airflow, extraction and their two ramps — extracted to
        # _resolve_airflow_extraction (banc 2026-08-05), see that method for
        # the doctrine comments (airflow-dependency-scaled base, the
        # Maillard Air Ramp opening ~40% of the total rise, and the
        # Development Ramp's burner-hold/air-support coupling).
        _airflow_ext = self._resolve_airflow_extraction(
            airwave_present=self._airwave_present,
            airflow_dependency_index=_airflow_dep_idx, humidity=humidity,
            ambient_humidity=ambient_humidity,
            inlet_air_mode=(getattr(ctx, "inlet_air_mode", "push") if ctx is not None else "push"),
            airflow_resolution_pct=(ctx.airflow_resolution_pct if ctx else 5.0),
            dry_bt_temperature=dry_bt_temperature, fc_bt=fc_bt, pre_fc_c=_pre_fc_c,
            drop_bt_temperature=drop_bt_temperature, to_native=_to_native,
            heater_pre_fc=heater_pre_fc, heater_dev=heater_dev,
            has_heater_control=_has_heater, heater_resolution_pct=_heater_res,
            dev_trajectory_learned=(history.get("dev_trajectory_learned") if history else None),
            dev_traj_samples=(int(history.get("dev_traj_samples", 0) or 0) if history else 0))
        airflow = _airflow_ext.airflow
        extraction = _airflow_ext.extraction
        airwave_mode = _airflow_ext.airwave_mode
        air_ramp = _airflow_ext.air_ramp
        _dev_ramp = _airflow_ext.dev_ramp
        _dev_ramp_source = _airflow_ext.dev_ramp_source

        # Generate planned BT curve waypoints (PCHIP interpolation) ---
        # All anchors are °C (internal frame); the curve comes back °C-pure.
        bt_plan_curve = self.generate_bt_curve_waypoints(
            charge_temperature      = charge_bt_temperature,
            dry_temperature         =   dry_bt_temperature,
            fc_temperature          = fc_bt,
            drop_temperature        = drop_bt_temperature,
            dry_time_min         = dry_time_min,
            fc_time_min          = fc_time_min,
            drop_time_min        = drop_time_min,
            charge_weight           = charge_weight,
            ror_maillard            = ror_maillard,
            ror_dev_avg             = dev_ror,
            drop_ror                = drop_ror,
            expected_tp_bt          = _expected_tp_bt,
        )

        # ── Vérification RoR du Maillard (banc 2026-08-05) ────────────────────
        # Étape strictement DIAGNOSTIQUE, extraite en méthode pure — voir
        # _verify_maillard_ror pour la doctrine complète (aucune durée n'est
        # jamais dérivée d'un RoR).
        ror_fc_c, _mai_conflict, _mai_note = self._verify_maillard_ror(
            curve=bt_plan_curve, dry_time_min=dry_time_min,
            maillard_time_min=maillard_time_min, ma_bt_temperature=ma_bt_temperature,
            ror_maillard=ror_maillard, heater_dry=heater_dry, heater_pre_fc=heater_pre_fc,
            ror_scale=_ror_scale, mode=self.mode,
            decay_k=(float(ctx.maillard_ror_decay) if ctx is not None else 2.0))
        if _mai_note and history is not None:
            history["actions"] = (history.get("actions") or []) + [_mai_note]

        # ── Confiance du plan & seuils adaptatifs, note heat-soak — extracted
        # to _resolve_plan_confidence (banc 2026-08-05), see that method for
        # the doctrine comments (design validé 2026-07-04).
        _plan_conf = self._resolve_plan_confidence(
            fc_source=fc_source, timing_source=timing_source, drop_source=drop_source,
            fc_bt_mad_c=(history.get("fc_bt_mad_c") if history else None),
            soak_dcharge_c=_soak_dcharge_c, soak_dheater_pct=_soak_dheater,
            minutes_since_last_drop=minutes_since_last_drop, ror_scale=_ror_scale)
        _conf_level = _plan_conf.level
        _tol_factor = _plan_conf.tol_factor
        _conf_display = _plan_conf.display
        _soak_note = _plan_conf.soak_note

        # ── Replan context (°C machine state) ────────────────────────────────
        # Everything replan_from_milestone needs to re-anchor the remaining
        # curve mid-roast without re-running the history/grid analysis.
        # Captured BEFORE the output boundary so the anchors stay °C-pure
        # (doctrine: °C internal everywhere, single conversion at the edge).
        _replan_ctx: dict[str, Any] = {
            "unit_f":          _is_fahrenheit,
            "anchors_c":       [dict(_wp) for _wp in bt_plan_curve["waypoints"]],
            "ror_maillard_c":  ror_maillard,
            # pente du séchage — convertit les 30 s de tenue du feu en BT au replan
            "dry_ror_c":       dry_ror_average,
            "dev_ror_c":       dev_ror,
            "drop_ror_c":      drop_ror,
            "dev_window_min":  (float(roast_constraints.development_time[0]),
                                float(roast_constraints.development_time[1])),
            "dev_time_min":    float(dev_time_min),   # post-FC duration held by the re-fit (owner ruling 2026-08-04)
            "mai_window_min":  (float(roast_constraints.maillard_time[0]),
                                float(roast_constraints.maillard_time[1])),
            "fc_anticipation_sec": fc_anticipation_sec,
            "has_heater":      _has_heater,
            "heater_res":      _heater_res,
            "heater_max_pct":  _heater_max_pct,      # hardware ceiling — see Roaster.heater_max_pct
            "heater_dry_pct":  heater_dry,          ## TILAU ## requis par l'escalier progressif au replan
            "heater_maillard_pct": heater_maillard,
            "heater_dev_pct":  heater_dev,
            "heater_pre_fc_pct": heater_pre_fc,     # item C : palier pre-FC (FC appris)
            # geste préventif anti-flick au DE — appris ; 0.0 = pas de geste
            "heater_pre_de_pct": (heater_pre_de if _pre_de_active else 0.0),
            "pre_de_lead_sec":  _de_lead_sec,
            "pre_de_step_pct":  _de_step_pct,
            # Plancher de Maillard — le replan doit le tenir aussi :
            ## re-caler les seuils sur un vrai jalon ne doit pas ramener le feu
            ## sous la demande du grain. Deux scalaires, pas l'objet (le ctx est
            ## sérialisé dans le .alog).
            "maillard_floor_pct":     float(_floor.level_pct),
            "maillard_floor_release": float(_floor.release_fraction),
            "replans":         [],
        }

        # ── OUTPUT BOUNDARY (°F) ─────────────────────────────────────────────
        # Single conversion point: temperatures via _to_native, RoR ×1.8.
        # Consumers (assistant plan tracking, alarm factory, PDF, alog inject)
        # all read the plan in the Artisan display unit.
        if _is_fahrenheit:
            bt_plan_curve["bt_plan"]  = [round(fromCtoFstrict(v), 2) for v in bt_plan_curve["bt_plan"]]
            bt_plan_curve["ror_plan"] = [round(v * 1.8, 2) for v in bt_plan_curve["ror_plan"]]
            for _wp in bt_plan_curve["waypoints"]:
                _wp["bt"] = round(fromCtoFstrict(_wp["bt"]), 1)

        # history (uuid + quality + colour filtered) was computed early — see above.

        # Summary Output ---
        return  {
            "Bean Name": bean.name,
            "Weight": charge_weight,
            "Process Type": process_type,
            "Density": f"{density:.1f}",
            "Bean Humidity": f"{humidity:.1f}",
            "Water Activity Used": f"{wa:.3f}" if bean.water_activity > 0.0 else "Not measured",
            f"Ambient Temp": f"{_to_native(ambient_temp_c):.1f}",
            "Ambient Humidity": f"{ambient_humidity:.1f}",
            f"Charge Temp":    f"{_to_native(charge_bt_temperature):.1f}",
            f"End of Dry Temp": f"{_to_native(  dry_bt_temperature):.1f}",
            f"First Crack Temp": f"{_to_native(fc_bt):.1f}",
            "FC Temp Source": fc_source,  # "learned (n=N)" | "learned/grid blend (n=2)" | "grid"
            "Phase Timing Source": timing_source,  # same convention as FC Temp Source
            "Drop Temp Source": drop_source,       # "learned (n=N)" | "blend" | "grid" — colour feedback
            "Heater Source": heater_source,         # per-phase burner: learned from matched history | grid
            "Heater FC Source": heater_fc_source,   ## TILAU ## item C — palier pre-FC appris | grid (= calcul du plan)
            "Drop ROR Source": drop_ror_source,     ## TILAU ## item A — "grid" = table bonnes-pratiques
            "Plan Confidence": _conf_display,      # operator-facing (PDF, tooltips)
            # Seuils adaptatifs : bandes RoR relatives (sans unité) pour le
            # coach, deltas BT (unité native) pour l'adhérence EOR.
            "Plan Tolerances": {
                "level":        _conf_level,
                "ror_rel_ok":   round(0.15 * _tol_factor, 3),
                "ror_rel_warn": round(0.30 * _tol_factor, 3),
                "adher_ok":     round(3.0 * _tol_factor * _ror_scale, 1),
                "adher_warn":   round(7.0 * _tol_factor * _ror_scale, 1),
            },
            f"Drop Temp":      f"{_to_native(drop_bt_temperature):.1f}",
            "Dry Phase":self.format_time(dry_time_min),
            "Dry Phase %": f"{dry_phase_percent:.1f}", 
            "Maillard Phase":self.format_time(maillard_time_min),
            "Maillard Phase %": f"{maillard_phase_percent:.1f}", 
            "FC Time":self.format_time(fc_time_min),
            "Development Phase":self.format_time(dev_time_min), 
            "Development Phase %": f"{dev_phase_percent:.1f}", 
            "Total Time":self.format_time(drop_time_min),
            "Drum Speed (%) (Dry|Mai|Dev)": f"{' | '.join(drum_speed_pct)}",
            "Heater (%) (Dry|Mai|Dev)": f"{' | '.join(heater)}",
            "Airflow (%) (Dry|Mai|Dev)": f"{' | '.join(airflow)}",
            "Extraction (%) (Dry|Mai|Dev)": f"{' | '.join(extraction)}",
            "AirWave Mode (Dry|Mai|Dev)": f"{' | '.join(airwave_mode)}",
            "Target DTR": f"{dtr_achieved * 100.0:.1f}", # Resulting DTR — consequence of the retained durations, not a target (owner ruling 2026-08-04)
            f"ROR Dry End":         f"{dry_ror_average * _ror_scale:.0f}",
            f"ROR Dry Peak":        f"{dry_ror_peak * _ror_scale:.0f}",
            f"Target ROR Maillard": f"{ror_maillard * _ror_scale:.1f}",
            # Valeur d'ARRIVÉE du Maillard, déduite de la décroissance en
            # puissance k de la machine — la moyenne seule ne dit pas où on
            # atterrit, et c'est l'atterrissage qui décide du FC.
            f"Target ROR at FC": f"{ror_fc_c * _ror_scale:.1f}",
            "Maillard Conflict": _mai_conflict,   # "" | acceleration | crash | illegible
            f"Target ROR Dev (Avg)": f"{dev_ror * _ror_scale:.1f}",
            f"Target ROR at Drop":  f"{drop_ror * _ror_scale:.1f}",
            "Estimated TP":         f"{_to_native(tp_temperature):.1f}",
            "Heater at TP": f"{heater_tp:.0f}",
            # Anticipated Maillard→Dev heater steps, BT-triggered (native unit).
            # Consumed by TilauscopeAlarmFactory; empty when no heater control.
            "Heater Ramp": heater_ramp,
            "Dev Ramp": _dev_ramp,                     ## TILAU ## trajectoire dev continue
            "Air Ramp": air_ramp,                      ## TILAU ## montée airflow Maillard (mi-Mai→FC)
            "Dev Profile Source": _dev_ramp_source,    ## TILAU ## learned (n=N) | default
            "FC Anticipation (s)": f"{fc_anticipation_sec:.0f}",
            "Target Agtron": target_roast_category, # Use the determined category
            # Point 8: surface roaster capability flags so the UI/alarm factory
            # can adapt their behaviour without importing roasters.py.
            "Roaster": ctx.display_name if ctx else "Unknown",
            "Preheat Profile Available": ctx.supports_preheat_profiles if ctx else False,
            "Profile Replay Available":  ctx.supports_profile_replay  if ctx else False,
            "Drum Variable Speed":        _drum_variable,
            "notes": history["notes"] if history else None,
            "actions": ((((history["actions"] or []) if history else [])
                         + ([_soak_note] if _soak_note else [])) or None),
            # Correction back-to-back appliquée (deltas en unité native) — None
            # au batch 1 / attente longue. Affichée par la page preheat.
            "Heat Soak": ({"dcharge": round(_soak_dcharge_c * _ror_scale, 1),
                           "dheater": _soak_dheater,
                           "mins": round(float(minutes_since_last_drop), 1)}
                          if (_soak_dcharge_c < 0.0 and minutes_since_last_drop is not None) else None),
            "bt_plan_curve": bt_plan_curve,          # PCHIP planned BT curve + waypoints
            "_replan_ctx": _replan_ctx,              # °C state consumed by replan_from_milestone
            "_airwave_present": "yes" if self._airwave_present else "no",   # Whether AirWave extraction control is available (for UI and alarm logic)
        }, history["graph"] if history else None, history["crashes"] if history else None, history["flicks"] if history else None

    # ── Mid-roast re-anchoring (« plan vivant ») ─────────────────────────────
    #
    # Invariant: TEMPERATURES are targets (preserved), TIMES are predictions
    # (re-fitted). A real milestone replaces its planned anchor and the
    # remaining anchors are re-projected — the delay is ABSORBED (RoR targets
    # kept), never chased by compressing the remaining phases. Artisan alarms
    # injected at start are BT-keyed, so they stay valid without mutation;
    # only the guidance-side plan dict is rebuilt.

    _REPLAN_MILESTONES: Final = ("tp", "dry_end", "fc_start")

    @staticmethod
    def _fmt_signed_sec(delta_min: float) -> str:
        """+1.5 min → '+1:30' ; −0.4 → '−0:24' (shift vs the planned anchor)."""
        sign = "+" if delta_min >= 0 else "−"
        m, s = divmod(int(round(abs(delta_min) * 60.0)), 60)
        return f"{sign}{m}:{s:02d}"

    def _refit_development(self, ctx: dict, t_fc_min: float, fc_bt_c: float) -> "str | None":
        """
        Re-project the development segment from a (possibly re-anchored) FC.

        Owner ruling (2026-08-04): the post-FC DURATION is HELD — it is the
        one the plan was built with, not renegotiated to steer the DTR back
        inside a style band. First crack landing early or late shifts the
        whole tail in absolute time; the development rate of rise is the
        derived quantity, free to come out high or low. Mutates ctx
        anchors/RoRs in place (°C frame). Returns an operator-facing warning
        when the resulting dev RoR signals the front of the roast is off,
        never based on the DTR.
        """
        by_key = {a.get("key"): a for a in ctx["anchors_c"]}
        a_pre, a_drop = by_key["pre_drop"], by_key["drop"]
        drop_bt = float(a_drop["bt"])
        rise = drop_bt - fc_bt_c            # °C left to gain in development
        dev_ror_cur  = max(0.5, float(ctx["dev_ror_c"]))

        # Post-FC duration is HELD (owner ruling 2026-08-04). First crack landing
        # early or late shifts the whole tail in absolute time — that is accepted.
        # The development rate of rise is what gives, not the duration: steering the
        # duration to land the DTR inside a band was targeting a consequence.
        # repli mi-fenêtre pour les vieux dicts de plan sans la clé
        ## (mêmes vieux plans que le repli heater_max_pct ci-dessous).
        _w_lo, _w_hi = ctx["dev_window_min"]
        t_dev = float(ctx.get("dev_time_min", (_w_lo + _w_hi) * 0.5))
        dev_ror_new = rise / t_dev if t_dev > 0 else dev_ror_cur

        ctx["dev_ror_c"] = dev_ror_new
        # Drop RoR doctrine: capped at dev RoR − 0.3, collapsible floor.
        ctx["drop_ror_c"] = min(float(ctx["drop_ror_c"]), max(0.3, dev_ror_new - 0.3))

        t_drop = t_fc_min + t_dev
        a_drop["time_min"] = round(t_drop, 2)
        # Pre-drop anchor: same deceleration model as the initial curve.
        t_pre = t_drop - 0.5
        if t_pre <= t_fc_min + 0.1:
            t_pre = (t_fc_min + t_drop) / 2.0
        ror_pre_drop_mean = (dev_ror_new + float(ctx["drop_ror_c"])) * 0.5
        a_pre["time_min"] = round(t_pre, 2)
        a_pre["bt"]       = round(drop_bt - ror_pre_drop_mean * (t_drop - t_pre), 1)

        dtr_final = t_dev / t_drop * 100.0 if t_drop > 0 else 0.0
        if dev_ror_new < 0.5:
            return QApplication.translate(
                "tilauscope_roast_plan",
                "First crack landed hot relative to the drop target — only {0}°/min of rise "
                "left over the planned {1} of development (projected DTR {2}%). Watch for a flat "
                "or falling curve into drop.").format(
                f"{dev_ror_new:.1f}", self.format_time(t_dev), f"{dtr_final:.1f}")
        if dev_ror_new > dev_ror_cur * 1.5:
            return QApplication.translate(
                "tilauscope_roast_plan",
                "First crack landed cold relative to the drop target — reaching it in the "
                "planned {0} of development now needs a steep {1}°/min climb (projected DTR "
                "{2}%). Watch for a rushed development.").format(
                self.format_time(t_dev), f"{dev_ror_new:.1f}", f"{dtr_final:.1f}")
        return None

    def _build_heater_ramp_c(self, tp_bt_c: float, de_bt_c: float, fc_bt_c: float,
                             ror_maillard_c: float, fc_anticipation_sec: float,
                             heater_res: float, h_dry: float, h_mai: float,
                             h_pre_fc: float, to_native,
                             heater_max_pct: float = 100.0,
                             floor: "FloorProfile | None" = None,
                             dry_end_ror_c: float = 0.0,
                             pre_de_pct: float = 0.0,
                             pre_de_lead_sec: float = _HOLD_LEAD_SEC,
                             pre_de_step_pct: float = 5.0) -> "list[dict]":
        """## TILAU ## Escalier heater PROGRESSIF ancré MI-PHASE (item C,
        Bench-Integration, décision Tilau 2026-07-12). Les valeurs apprises
        (h_dry, h_mai) sont échantillonnées au MILIEU de leur phase — l'ancien
        escalier les ancrait en DÉBUT de phase (h_mai dès le DRY END), soit une
        demi-phase trop bas trop tôt (défaut §10 confirmé par l'étude 2).
        Nouvelle géométrie, validée sur le gabarit mesuré (75 mi-DRY · 70 DRYe ·
        65 mi-MAI · 50 FC · 45 dev) :
          - h_dry TENU de la charge à ~75 % du séchage ;
          - descente en marches d'une résolution atteignant h_mai à MI-Maillard ;
          - puis vers h_pre_fc (feu au FC appris de l'historique, backup calcul
            du plan) atteint ~fc_anticipation s avant le FC.
        PARTAGÉ par la génération ET le replan (le plan vivant garde la forme).
        Toutes les entrées BT en montant → sécurité franchissement.

        `floor` (plancher de Maillard, tilauscope/bean_energy.py) borne chaque
        marche par le BAS entre le DRY END et le FC : les ancres sont déjà
        relevées par l'appelant, mais l'interpolation qui les relie peut encore
        passer sous la partie plate du plancher. Absent = aucune contrainte.

        `pre_de_pct` : geste PRÉVENTIF anti-flick au DRY END, quand l'historique
        montre que l'opérateur baisse le feu avant la fin du séchage. C'est SA
        valeur apprise, pas un pourcentage deviné — un flick au DE est un défaut
        de setup connu du grain, et le % qui le corrige lui appartient. Posé à
        `_HOLD_LEAD_SEC` du DE ; la descente repart de là. 0 = pas de geste."""
        ramp: list[dict] = []
        _step = max(1.0, float(heater_res))
        _tp_c = float(tp_bt_c)
        _de_c = float(de_bt_c)
        _lead_c = max(0.0, float(ror_maillard_c)) * float(fc_anticipation_sec) / 60.0
        _pre_fc_c = max(_de_c + 1.0, float(fc_bt_c) - _lead_c)
        # mi-Maillard en BT, gardé sous le palier pre-FC (ordre strict des ancres)
        _mid_mai_c = min((_de_c + float(fc_bt_c)) / 2.0, _pre_fc_c - 0.5)
        _h_tp  = round(float(h_dry) / _step) * _step
        _h_mid = round(float(h_mai) / _step) * _step
        _h_pfc = round(float(h_pre_fc) / _step) * _step
        # Feu de séchage TENU jusqu'à ~30 s du DRY END (doctrine Tilau : « le feu
        # au DE vient du réglage initial, on n'y touche pas avant disons 30 s
        # avant le DE »). L'ancienne géométrie le lâchait à 75 % du SÉCHAGE en BT,
        # soit 141 °C pour un DE à 150 — le dernier quart du séchage, bien trop
        # tôt. Les 30 s sont converties en BT par la PENTE DU SÉCHAGE, pas par une
        # constante : c'est elle qui dit combien de degrés valent 30 s ici. C'est
        # la pente MOYENNE du séchage, pas celle de sa sortie (la vraie R_DE ne
        # se lit que sur la courbe, construite plus tard) : elle la surestime un
        # peu, donc on lâche ~1 °C trop tôt — dans le sens de l'anticipation, que
        # les 25-45 s de latence du brûleur demandent de toute façon.
        # Repli sur l'ancienne fraction si la pente est absente.
        # Valeur apprise AU DRY END : ce n'est PAS un geste unique, c'est le
        # point d'arrivée du séchage. La main de l'opérateur y descend
        # progressivement — l'émettre d'un bloc produirait des sauts de 25 %,
        # illisibles et infaisables. Elle devient donc un 4e point d'ancrage de
        # l'escalier, entre la médiane de séchage et le mi-Maillard.
        _h_pre_de = round(float(pre_de_pct) / _step) * _step
        _pre_de_on = (pre_de_pct > 0.0 and _h_pre_de < _h_tp - 1e-6
                      and _h_pre_de >= _h_mid - 1e-6)
        _h_head = _h_pre_de if _pre_de_on else _h_tp
        # Rejeté quand la valeur apprise passe SOUS le plancher de Maillard : le
        # plancher ne peut que relever, donc il n'y a pas de creux à jouer.

        # L'avance apprise n'a de sens QUE si l'ancre apprise est retenue : sans
        # geste à jouer, reculer la tenue du feu la ferait descendre plus tôt
        # pour rien.
        _lead_sec = float(pre_de_lead_sec) if _pre_de_on else _HOLD_LEAD_SEC
        _dry_lead_c = max(0.0, float(dry_end_ror_c)) * _lead_sec / 60.0
        # Nombre de crans nécessaires pour rejoindre la valeur apprise au DE
        # sans dépasser la limite d'observabilité (un cran de 5 % par 30 s) :
        # la tenue démarre d'autant plus tôt que la baisse apprise est franche.
        # L'avance apprise EST la durée de la descente : plus besoin de la
        # déduire du nombre de crans. Repli doctrine quand rien n'est appris.
        _hold_c = (_de_c - _dry_lead_c if _dry_lead_c > 0.0
                   else _tp_c + 0.75 * max(0.0, _de_c - _tp_c))
        _hold_c = min(max(_hold_c, _tp_c + 0.1), _mid_mai_c - 0.5)

        def _floor_at(bt_c: float) -> float:
            # Le domaine du plancher court du DRY END au palier PRE-FC (pas au
            # FC) : sa fin de courbe, relâchée d'un cran, EST la baisse
            # anti-rebond qui se pose sur ce palier. Au-delà, la transition
            # exothermique n'est plus sous l'autorité du plancher.
            # AVANT le DRY END il vaut son niveau plat (at() borne la fraction) :
            # le couper à 0 ferait remonter la courbe effective d'un cran au DRY
            # END, et tout le placement des marches suppose une descente
            # monotone. Physiquement c'est le même énoncé — le feu ne descend pas
            # sous la demande du grain juste avant d'entrer en Maillard.
            if floor is None:
                return 0.0
            _mai_span = _pre_fc_c - _de_c
            if _mai_span <= 0.0:
                return floor.at(1.0)
            return floor.at((bt_c - _de_c) / _mai_span)

        def _pw(bt_c: float) -> float:
            if bt_c <= _hold_c:
                return _h_tp
            if _pre_de_on and bt_c <= _de_c:
                # segment de SÉCHAGE : rejoint la valeur apprise au DRY END
                f = (bt_c - _hold_c) / (_de_c - _hold_c) if _de_c > _hold_c else 1.0
                return _h_tp + (_h_head - _h_tp) * max(0.0, min(1.0, f))
            _from_c = _de_c if _pre_de_on else _hold_c
            if bt_c <= _mid_mai_c:
                f = (bt_c - _from_c) / (_mid_mai_c - _from_c) if _mid_mai_c > _from_c else 1.0
                return _h_head + (_h_mid - _h_head) * max(0.0, min(1.0, f))
            f = (bt_c - _mid_mai_c) / (_pre_fc_c - _mid_mai_c) if _pre_fc_c > _mid_mai_c else 1.0
            return _h_mid + (_h_pfc - _h_mid) * max(0.0, min(1.0, f))

        _span = _pre_fc_c - _tp_c
        _move = abs(_h_head - _h_tp) + abs(_h_mid - _h_head) + abs(_h_pfc - _h_mid)
        if _span <= 1.0 or _move < _step - 1e-6:
            return ramp
        if _h_tp >= _h_head >= _h_mid >= _h_pfc:
            # ── Émission PAR VALEUR (marches ≤ 5 %, étude 3) ────────────────── ## TILAU ##
            # L'ancien échantillonnage uniforme en BT plafonné à 12 entrées
            # produisait des marches de 6-10 % dans le segment raide de fin de
            # Maillard — le saut brutal que la rampe existe pour éviter. Chaque
            # palier est placé au BT où la descente linéaire atteint son seuil
            # d'arrondi (v + pas/2), comme l'Air Ramp : dense où c'est raide.
            #  Les marches sont placées sur la courbe EFFECTIVE
            # max(échelle, plancher) : chercher leur BT sur la seule échelle
            # linéaire puis relever la valeur au plancher les posait au mauvais
            # endroit — le dernier palier n'atteignait jamais h_pre_fc et laissait
            # un saut invisible au FC, là où la Dev Ramp reprend. Recherche
            # numérique : la courbe effective est monotone mais pas inversible.
            def _eff(bt_c: float) -> float:
                return max(_pw(bt_c), _floor_at(bt_c))
            _SCAN = 240
            def _first_bt(fn, target: float) -> float:
                # premier BT où fn passe sous target (fn décroissante)
                for _i in range(_SCAN + 1):
                    _b = _hold_c + (_pre_fc_c - _hold_c) * _i / _SCAN
                    if fn(_b) <= target:
                        return _b
                return _pre_fc_c
            _step_val = max(_step, min(5.0, _move))
            # Sur la descente APPRISE avant le DRY END, la granularité est celle
            # de la main de l'opérateur (1-3 %), pas le plafond d'observabilité.
            _step_head = max(_step, min(float(pre_de_step_pct), _step_val))
            _h_start = round(_eff(_hold_c) / _step) * _step
            _h_end   = max(_h_pfc, math.ceil(_floor_at(_pre_fc_c) / _step - 1e-9) * _step)
            _levels: list[float] = []
            _v = _h_start - (_step_head if _pre_de_on else _step_val)
            while _v > _h_end + 1e-6:
                _levels.append(_v)
                _v -= (_step_head if _pre_de_on and _v > _h_head - 1e-6 else _step_val)
            _levels.append(_h_end)
            _prev_h = _h_start   # le feu de séchage tient déjà cette valeur
            for _lv in _levels:
                # Seuil d'arrondi = MOITIÉ DE L'ÉCART RÉEL au palier précédent.
                # Le dernier palier (h_pre_fc / fin de plancher) n'est pas sur la
                # grille des _step_val : lui appliquer un demi-pas plein le posait
                # avant que la courbe n'ait commencé à y descendre — jusqu'à
                # l'annoncer pendant le SÉCHAGE.
                _gap = max(_step, _prev_h - _lv)
                _bt_i = _first_bt(_eff, _lv + _gap / 2.0)
                # L'anticipation est un confort (le brûleur a 25-45 s de lag),
                # PAS une licence pour passer sous le plancher : quand c'est le
                # plancher qui borne, la baisse tombe là où il la libère.
                if _floor_at(_bt_i) > _lv + 1e-9:
                    _bt_i = _first_bt(_floor_at, _lv)
                _bt_i = min(_pre_fc_c, max(_hold_c + 0.1, _bt_i))
                _h_i = max(0.0, min(heater_max_pct, round(_lv / _step) * _step))
                if _h_i >= _prev_h - 1e-6:
                    continue   # marche absorbée par le plancher : rien à annoncer
                if ramp and _bt_i <= ramp[-1]["bt_c"] + 1e-6:
                    _bt_i = ramp[-1]["bt_c"] + 0.5   # BT strictement croissants
                ramp.append({"bt_c": _bt_i, "heater": int(_h_i)})
                _prev_h = _h_i
            for _e in ramp:
                _e["bt"] = round(to_native(_e.pop("bt_c")), 1)
            return ramp
        # forme non monotone (dégénérée) : repli sur l'échantillonnage uniforme
        _n = int(max(1, min(12, round(_move / _step))))
        _prev_h = _h_tp
        for _i in range(1, _n + 1):
            _bt_i = _tp_c + _span * (_i / _n)
            _h_i = max(0.0, min(heater_max_pct, round(_pw(_bt_i) / _step) * _step))
            _h_i = min(heater_max_pct,
                       max(_h_i, math.ceil(_floor_at(_bt_i) / _step - 1e-9) * _step))
            if abs(_h_i - _prev_h) >= _step - 1e-6:   # a bougé d'≥ 1 pas
                ramp.append({"bt": round(to_native(_bt_i), 1), "heater": int(_h_i)})
                _prev_h = _h_i
        return ramp

    def replan_from_milestone(self, plan: dict, milestone: str,
                              t_actual_min: float, bt_actual_native: float) -> dict:
        """
        Re-anchor the planned BT curve on a real milestone (t, BT) and return
        a NEW plan dict — the input plan and its nested structures are never
        mutated (the assistant keeps the initial plan for the EOR report).

        milestone        : "tp" | "dry_end" | "fc_start"
        t_actual_min     : minutes since CHARGE
        bt_actual_native : BT at the milestone, in the plan's native unit

        Returns the input plan unchanged when the milestone is implausible
        (mis-marked event) or the replan context is missing (old plan dict).
        """
        try:
            src_ctx = plan.get("_replan_ctx") if plan else None
            if not src_ctx or milestone not in self._REPLAN_MILESTONES:
                return plan
            ctx    = copy.deepcopy(src_ctx)
            unit_f = bool(ctx.get("unit_f"))
            bt_c   = float(fromFtoCstrict(bt_actual_native)) if unit_f else float(bt_actual_native)
            t_min  = float(t_actual_min)
            _scale = 1.8 if unit_f else 1.0

            def _nat(v_c: float) -> float:
                return fromCtoFstrict(v_c) if unit_f else v_c

            anchors = ctx["anchors_c"]
            by_key  = {a.get("key"): a for a in anchors}
            a_charge, a_tp, a_dry = by_key.get("charge"), by_key.get("tp"), by_key.get("dry_end")
            a_fc, a_pre, a_drop   = by_key.get("fc_start"), by_key.get("pre_drop"), by_key.get("drop")
            if None in (a_charge, a_tp, a_dry, a_fc, a_pre, a_drop):
                return plan

            _old_dry_t, _old_fc_t = float(a_dry["time_min"]), float(a_fc["time_min"])
            warning: "str | None" = None

            if milestone == "tp":
                # Plausibility: inside a generous dip window, well before dry end.
                if not (0.4 <= t_min <= 2.5
                        and a_charge["bt"] * 0.35 <= bt_c <= a_charge["bt"] * 0.80
                        and t_min < float(a_dry["time_min"]) - 0.5):
                    _logd.info(f"replan[tp]: implausible anchor t={t_min:.2f}min bt={bt_c:.1f}°C — skipped")
                    return plan
                # Anchor swap only, no downstream propagation: the modeled TP
                # is replaced by the measured one so the live plan reference
                # (_plan_curve_ref) is valid from the first minute.
                a_tp["time_min"], a_tp["bt"] = round(t_min, 2), round(bt_c, 1)

            elif milestone == "dry_end":
                # Same plausibility gates as the history timing calibration.
                if not (2.5 <= t_min <= 8.0
                        and abs(bt_c - float(a_dry["bt"])) <= 20.0
                        and t_min > float(a_tp["time_min"]) + 0.25
                        and float(a_fc["bt"]) - bt_c >= 5.0):
                    _logd.info(f"replan[dry_end]: implausible anchor t={t_min:.2f}min bt={bt_c:.1f}°C — skipped")
                    return plan
                a_dry["time_min"], a_dry["bt"] = round(t_min, 2), round(bt_c, 1)
                # Absorb the shift: keep the Maillard RoR target and re-project
                # t_fc from it (never compress the remaining phases to chase
                # the original clock), clamped to the style window ± margin.
                ror_m = max(0.5, float(ctx["ror_maillard_c"]))
                t_mai = (float(a_fc["bt"]) - bt_c) / ror_m
                w_lo, w_hi = ctx["mai_window_min"]
                t_mai = min(max(t_mai, w_lo - 0.5), w_hi + 0.5)
                a_fc["time_min"] = round(t_min + t_mai, 2)
                ctx["ror_maillard_c"] = (float(a_fc["bt"]) - bt_c) / t_mai
                warning = self._refit_development(ctx, float(a_fc["time_min"]), float(a_fc["bt"]))

            else:  # fc_start
                # Plausibility: same 175–212 °C window as the FC learning gate,
                # and the drop target must still be meaningfully above.
                if not (175.0 <= bt_c <= 212.0
                        and float(a_dry["time_min"]) + 0.25 < t_min <= 25.0
                        and bt_c <= float(a_drop["bt"]) - 2.0):
                    _logd.info(f"replan[fc_start]: implausible anchor t={t_min:.2f}min bt={bt_c:.1f}°C — skipped")
                    return plan
                a_fc["time_min"], a_fc["bt"] = round(t_min, 2), round(bt_c, 1)
                warning = self._refit_development(ctx, t_min, bt_c)

            # Post-fit sanity: anchor times strictly increasing, and BT rising
            # monotonically after the TP (the assistant's inverse lookup in
            # _plan_curve_ref relies on it — PCHIP preserves anchor monotony).
            times = [float(a["time_min"]) for a in anchors]
            bts   = [float(a["bt"]) for a in anchors[1:]]   # tp .. drop
            if (any(t2 - t1 < 0.05 for t1, t2 in zip(times, times[1:]))
                    or any(b2 - b1 < 0.5 for b1, b2 in zip(bts, bts[1:]))):
                _logd.warning(f"replan[{milestone}]: non-monotonic anchors after re-fit — keeping current plan")
                return plan

            curve = self._build_pchip_curve([dict(a) for a in anchors])

            # Re-anchored phase durations (°C frame, minutes).
            t_dry, t_fc, t_drop = float(a_dry["time_min"]), float(a_fc["time_min"]), float(a_drop["time_min"])
            t_mai, t_dev = t_fc - t_dry, t_drop - t_fc
            dry_pct = round(t_dry / t_drop * 100.0, 0) if t_drop > 0 else 0.0
            mai_pct = round(t_mai / t_drop * 100.0, 0) if t_drop > 0 else 0.0
            dev_pct = 100.0 - dry_pct - mai_pct
            dtr_calc = (t_dev / t_drop * 100.0) if t_drop > 0 else 0.0

            # Heater ramp rebuilt avec LE MÊME escalier progressif TP→pre-FC que  ## TILAU ##
            # la génération (helper partagé) — jamais l'ancienne rampe grossière  ## TILAU ##
            # 2-points qui réintroduisait le saut brutal pre-FC. Au replan « tp » ## TILAU ##
            # (swap d'ancre seul) on N'Y TOUCHE PAS : l'escalier initial est déjà ## TILAU ##
            # correct — le rebuild coarse écrasait tout (« le feu ne bouge plus »).## TILAU ##
            heater_ramp: list[dict] = []
            if milestone != "tp" and ctx.get("has_heater"):
                heater_ramp = self._build_heater_ramp_c(
                    float(a_tp["bt"]), float(a_dry["bt"]), float(a_fc["bt"]),
                    float(ctx["ror_maillard_c"]), float(ctx["fc_anticipation_sec"]),
                    float(ctx.get("heater_res", 1.0)),
                    float(ctx.get("heater_dry_pct", 0.0)),
                    float(ctx.get("heater_maillard_pct", 0.0)),
                    ## TILAU ## item C : palier pre-FC (FC appris) ; repli dev
                    ## pour les vieux dicts de plan sans la clé.
                    float(ctx.get("heater_pre_fc_pct",
                                  ctx.get("heater_dev_pct", 0.0))), _nat,
                    # hardware ceiling ; repli 100.0 pour les vieux
                    ## dicts de plan sans la clé (pas de ceiling connu).
                    heater_max_pct=float(ctx.get("heater_max_pct", 100.0)),
                    # pente de séchage : convertit les 30 s de tenue en BT ;
                    # absente des vieux dicts de plan → repli sur la fraction
                    dry_end_ror_c=float(ctx.get("dry_ror_c", 0.0) or 0.0),
                    # geste préventif appris ; absent des vieux plans → aucun
                    pre_de_pct=float(ctx.get("heater_pre_de_pct", 0.0) or 0.0),
                    pre_de_lead_sec=float(ctx.get("pre_de_lead_sec", _HOLD_LEAD_SEC)),
                    pre_de_step_pct=float(ctx.get("pre_de_step_pct", 5.0)),
                    # plancher de Maillard reconstruit depuis le ctx ;
                    ## absent des vieux dicts de plan → aucune contrainte.
                    floor=(FloorProfile(
                        level_pct=float(ctx["maillard_floor_pct"]),
                        release_fraction=float(ctx["maillard_floor_release"]))
                        if ctx.get("maillard_floor_pct") is not None else None))

            # Operator-facing note (shown once by the assistant coach line).
            if milestone == "tp":
                note = QApplication.translate(
                    "tilauscope_roast_plan",
                    "Plan re-anchored at TP ({0}° @ {1})").format(
                    f"{_nat(bt_c):.0f}", self.format_time(t_min))
            elif milestone == "dry_end":
                note = QApplication.translate(
                    "tilauscope_roast_plan",
                    "Plan re-anchored at DRY END ({0} vs plan) — FC forecast {1}, projected DTR {2}%").format(
                    self._fmt_signed_sec(t_min - _old_dry_t), self.format_time(t_fc), f"{dtr_calc:.1f}")
            else:
                note = QApplication.translate(
                    "tilauscope_roast_plan",
                    "Plan re-anchored at FC ({0} vs plan) — DROP forecast {1}, projected DTR {2}%").format(
                    self._fmt_signed_sec(t_min - _old_fc_t), self.format_time(t_drop), f"{dtr_calc:.1f}")

            # ── OUTPUT BOUNDARY (°F) — same single conversion point as the
            # initial plan: the °F re-fitted plan is the exact conversion of
            # the °C one (test_f_mode invariant extends to replans).
            if unit_f:
                curve["bt_plan"]  = [round(fromCtoFstrict(v), 2) for v in curve["bt_plan"]]
                curve["ror_plan"] = [round(v * 1.8, 2) for v in curve["ror_plan"]]
                for _wp in curve["waypoints"]:
                    _wp["bt"] = round(fromCtoFstrict(_wp["bt"]), 1)

            ctx["replans"].append({"milestone": milestone,
                                   "t_min": round(t_min, 3),
                                   "bt_native": round(float(bt_actual_native), 2)})

            new_plan = dict(plan)   # shallow copy; every changed key is rebound to a fresh object
            new_plan["_replan_ctx"]          = ctx
            new_plan["bt_plan_curve"]        = curve
            new_plan["End of Dry Temp"]      = f"{_nat(float(a_dry['bt'])):.1f}"
            new_plan["First Crack Temp"]     = f"{_nat(float(a_fc['bt'])):.1f}"
            new_plan["Estimated TP"]         = f"{_nat(float(a_tp['bt'])):.1f}"
            new_plan["Dry Phase"]            = self.format_time(t_dry)
            new_plan["Dry Phase %"]          = f"{dry_pct:.1f}"
            new_plan["Maillard Phase"]       = self.format_time(t_mai)
            new_plan["Maillard Phase %"]     = f"{mai_pct:.1f}"
            new_plan["FC Time"]              = self.format_time(t_fc)
            new_plan["Development Phase"]    = self.format_time(t_dev)
            new_plan["Development Phase %"]  = f"{dev_pct:.1f}"
            new_plan["Total Time"]           = self.format_time(t_drop)
            new_plan["Target DTR"] = f"{dtr_calc:.1f}"  # resulting DTR, re-fitted at replan
            new_plan["Target ROR Maillard"]  = f"{float(ctx['ror_maillard_c']) * _scale:.1f}"
            new_plan["Target ROR Dev (Avg)"] = f"{float(ctx['dev_ror_c']) * _scale:.1f}"
            new_plan["Target ROR at Drop"]   = f"{float(ctx['drop_ror_c']) * _scale:.1f}"
            if milestone != "tp" and ctx.get("has_heater"):
                new_plan["Heater Ramp"] = heater_ramp   ## TILAU ## préserve l'escalier au replan TP
            ## TILAU ## Dev Ramp : les consignes de leviers apprises ne bougent
            ## pas, mais leurs seuils BT suivent les ancres FC/DROP re-fittées
            ## (chaque étage garde sa fraction "_f" ; même géométrie qu'à la
            ## génération : fc → drop−3°).
            if plan.get("Dev Ramp"):
                _fc_c, _drop_c = float(a_fc["bt"]), float(a_drop["bt"])
                new_plan["Dev Ramp"] = [
                    {**_e, "bt": round(_nat(_fc_c + (_drop_c - 3.0 - _fc_c)
                                            * float(_e.get("_f", 0.5))), 1)}
                    for _e in plan["Dev Ramp"]]
            ## TILAU ## Air Ramp (Maillard) : chaque palier garde sa fraction "_af"
            ## (mi-Maillard→pre-FC) et son seuil BT suit les ancres re-fittées —
            ## même traitement que le Dev Ramp, plus de re-répartition uniforme
            ## qui déplaçait les paliers hors de leur place réelle.
            if plan.get("Air Ramp"):
                _mid_c = (float(a_dry["bt"]) + float(a_fc["bt"])) / 2.0
                _lead_c = max(0.0, float(ctx["ror_maillard_c"])) * float(ctx["fc_anticipation_sec"]) / 60.0
                _pfc_c = max(_mid_c + 1.0, float(a_fc["bt"]) - _lead_c)
                new_plan["Air Ramp"] = [
                    {**_e, "bt": round(_nat(_mid_c + (_pfc_c - _mid_c) * float(_e.get("_af", 0.5))), 1)}
                    for _e in plan["Air Ramp"]]
            new_plan["Replan Source"]  = f"{milestone}@{self.format_time(t_min)}"
            new_plan["Replan Note"]    = note
            new_plan["Replan Warning"] = warning

            _logd.info(f"replan[{milestone}]: t={t_min:.2f}min bt={bt_c:.1f}°C → "
                       f"fc={t_fc:.2f}min drop={t_drop:.2f}min dtr={dtr_calc:.1f}%"
                       + (f" [{warning}]" if warning else ""))
            return new_plan
        except Exception as e:  # pylint: disable=broad-except
            _logd.warning(f"replan[{milestone}] failed ({e}) — keeping current plan")
            return plan


class TilauscopeAlarmFactory:
    def __init__(self, plan_data):
        self.plan = plan_data
        # code des actions Tilauscope/Artisan
        self.ACTION_LIST = {
        'Nothing': -1,
        'PopUp': 0,
        'Call Program': 1,
        'Event Button': 2,
        'Slider Air': 3,
        'Slider Drum': 4,
        'Slider Damper': 5,
        'Slider Burner': 6,
        'START': 7,
        'DRY END': 8,
        'FC START': 9,
        'FC END': 10,
        'SC START': 11,
        'SC END': 12,
        'DROP': 13,
        'COOL END': 14,
        'OFF': 15,
        'CHARGE': 16,
        'RampSoak ON': 17,
        'RampSoak OFF': 18,
        'PID ON': 19,
        'PID OFF': 20,
        'SV': 21,
        'Playback ON': 22,
        'Playback OFF': 23,
        'Set Canvas Color': 24,
        'Reset Canvas Color': 25,
        'Difluid Airwave command': 26,
        'TilauScope Ambient command': 27,
        'TilauScope command': 28
        }
        # Codes d'événements Tilauscope/Artisan
        self.EVENTS = {
        'ON': 9,
        'START': -1,
        'CHARGE': 0,
        'TP': 8,
        'DRY END': 1,
        'FC START': 2,
        'FC END': 3,
        'SC START': 4,
        'SC END': 5,
        'DROP': 6,
        'COOL END': 7,
        'If Alarm': 10
        }
        self._airwave_present:bool = self.plan.get("_airwave_present", "no") == "yes"
        self.alarms = self.generate()
        
    def _parse_val(self, key:str)->float:
        """Nettoie les chaînes comme '75%' ou '201.5' pour obtenir des nombres."""
        raw_val = self.plan.get(key, "0")
        if isinstance(raw_val, str):
            # On prend la première valeur si c'est une liste "75% | 60%"
            first_part = raw_val.split('|')[0].strip()
            return float(first_part.replace('%', ''))
        return float(raw_val)

    def _time_to_seconds(self, time_str:str)-> int:
        """Convertit 'MM:SS' en secondes totales."""
        try:
            m, s = map(int, time_str.split(':'))
            return m * 60 + s
        except Exception:
            return 0

    def generate(self):
        alarms  = {
            "alarmflags": [], "alarmguards": [], "alarmnegguards": [],
            "alarmtimes": [], "alarmoffsets": [], "alarmconds": [],
            "alarmsources": [], "alarmtemperatures": [], "alarmactions": [],
            "alarmbeep": [], "alarmstrings": []
        }

        # 0. PARAMÈTRES DE PHASE (Extraits du plan)
        def _pct_list(key: str) -> list[int | None]:
            """'70% | 55% | 40%' → [70, 55, 40] ; '--' (tambour fixe) → None."""
            out: list[int | None] = []
            for v in self.plan.get(key, "").split('|'):
                try:
                    out.append(int(v.strip().replace('%', '')))
                except ValueError:
                    out.append(None)
            return (out + [None, None, None])[:3]

        heaters = _pct_list("Heater (%) (Dry|Mai|Dev)")
        airflows = _pct_list("Airflow (%) (Dry|Mai|Dev)")
        drums = _pct_list("Drum Speed (%) (Dry|Mai|Dev)")
        extractions = (_pct_list("Extraction (%) (Dry|Mai|Dev)")
                       if self._airwave_present else [0, 0, 0])
         
        
        # 1. ON/START EVENT
        #             alarms, 1, 0, 0, EVENT                    , Time (s), Source  , =, 0.0, Action                   , Beep, Comment 
        self._add_row(alarms, 1, -1,-1, self.EVENTS.get("ON")   , 0.      , -3       , 2, 0.0, self.ACTION_LIST.get("PopUp"), 0,    "Starting PLAN"   )
        self._add_row(alarms, 1, -1,-1, self.EVENTS.get("ON")   , 0.      , -3       , 2, 0.0, self.ACTION_LIST.get("Slider Air"), 0,    "0"   )
        self._add_row(alarms, 1, -1,-1, self.EVENTS.get("START"), 0.      , -3       , 2, 0.0, self.ACTION_LIST.get("TilauScope command"), 0,    f"tilaupid(sv,{round(float(self.plan["Charge Temp"]),0)});tilaupid(start,)"   )        
        self._add_row(alarms, 1, -1,-1, self.EVENTS.get("START"), 0.      , -3       , 2, 0.0, self.ACTION_LIST.get("Slider Air"), 0,    "20"   )

        # 2. ÉVÉNEMENTS DE SÉCURITÉ & POPUPS
        # Alerte à CHARGE
        self._add_row(alarms, 1, -1,-1, self.EVENTS.get("CHARGE"), 0.      , -3       , 2, 0.0, self.ACTION_LIST.get("Slider Burner"), 0,    f"{heaters[0]}"   )
        self._add_row(alarms, 1, -1,-1, self.EVENTS.get("CHARGE"), 1.      , -3       , 2, 0.0, self.ACTION_LIST.get("Slider Air"),    0,    f"{airflows[0]}"   )
        if drums[0] is not None:   # tambour fixe → pas de ligne Slider Drum
            self._add_row(alarms, 1, -1,-1, self.EVENTS.get("CHARGE"), 2.      , -3       , 2, 0.0, self.ACTION_LIST.get("Slider Drum"),   0,    f"{drums[0]}"   )
        if self._airwave_present:
            self._add_row(alarms, 1, -1,-1, self.EVENTS.get("CHARGE"), 3., -3, 2, 0.0, self.ACTION_LIST.get("Slider Damper"),          0, f"{extractions[0]}")
            self._add_row(alarms, 1, -1,-1, self.EVENTS.get("CHARGE"), 4., -3, 2, 0.0, self.ACTION_LIST.get("Difluid Airwave command"), 0, "MODE FAN")

        # At TP
        self._add_row(alarms, 1, -1,-1, self.EVENTS.get("TP"),     0.      , -3       , 2, 0.0, self.ACTION_LIST.get("Slider Burner"), 0,    f"{self.plan["Heater at TP"]}"   )

        # Alerte fin de Séchage (DRY END)
        self._add_row(alarms, 1, -1,-1, self.EVENTS.get("DRY END"), 0.      , -3       , 2, 0.0, self.ACTION_LIST.get("Slider Burner"), 0,    f"{heaters[1]}"   )
        self._add_row(alarms, 1, -1,-1, self.EVENTS.get("DRY END"), 1.      , -3       , 2, 0.0, self.ACTION_LIST.get("Slider Air"),    0,    f"{airflows[1]}"   )
        ## TILAU ## item B (doctrine tambour) : plus AUCUNE ligne tambour in-roast
        ## (DRY END / FC START supprimées) — le tambour est posé UNE fois à la
        ## CHARGE (setup) et ne bouge qu'au DROP (refroidissement, grains sortis).
        if self._airwave_present:
            self._add_row(alarms, 1, -1,-1, self.EVENTS.get("DRY END"), 3., -3, 2, 0.0, self.ACTION_LIST.get("Slider Damper"),          0, f"{extractions[1]}")
            self._add_row(alarms, 1, -1,-1, self.EVENTS.get("DRY END"), 5., -3, 2, 0.0, self.ACTION_LIST.get("Difluid Airwave command"), 0, "MODE STD")
        self._add_row(alarms, 1, -1,-1, self.EVENTS.get("DRY END"), 4.      , -3       , 2, 0.0, self.ACTION_LIST.get("TilauScope Ambient command"),   0,    "CAL"   )
        self._add_row(alarms, 1, -1,-1, self.EVENTS.get("DRY END"), 45.     , -3       , 2, 0.0, self.ACTION_LIST.get("TilauScope Ambient command"),   0,    "START"   )

        # 2b. RAMPE HEATER ANTICIPÉE (Maillard → Dev)
        # Steps déclenchés sur seuil BT (source 1, cond 1 = "rises above"),
        # armés après DRY END. Le dernier step applique le heater de dev
        # AVANT le FC (anticipation ∝ inertie machine, calculée dans le plan).
        pre_fc_idx = -1
        heater_ramp = self.plan.get("Heater Ramp") or []
        for step in heater_ramp:
            pre_fc_idx = self._add_row(
                alarms, 1, -1, -1, self.EVENTS.get("DRY END"), 0., 1, 1,
                float(step["bt"]), self.ACTION_LIST.get("Slider Burner"), 0,
                f"{int(step['heater'])}")

        # Alerte First Crack (FC START)
        # Le step burner à FC n'est qu'un filet de sécurité : negguard sur le
        # dernier step de la rampe — il ne tire que si le seuil BT anticipé
        # n'a jamais été atteint (FC précoce, sonde en retard). Offset +1 s :
        # une ligne temporelle à offset 0 ne tire jamais (bloc offset sauté).
        self._add_row(alarms, 1, -1, pre_fc_idx, self.EVENTS.get("FC START"), 1.      , -3       , 2, 0.0, self.ACTION_LIST.get("Slider Burner"), 0,    f"{heaters[2]}"   )
        self._add_row(alarms, 1, -1,-1, self.EVENTS.get("FC START"), 1.      , -3       , 2, 0.0, self.ACTION_LIST.get("Slider Air"),    0,    f"{airflows[2]}"   )
        ## TILAU ## item B : ligne tambour FC START supprimée (doctrine setup).
        if self._airwave_present:
            self._add_row(alarms, 1, -1,-1, self.EVENTS.get("FC START"), 3., -3, 2, 0.0, self.ACTION_LIST.get("Slider Damper"),          0, f"{extractions[2]}")
            self._add_row(alarms, 1, -1,-1, self.EVENTS.get("FC START"), 5., -3, 2, 0.0, self.ACTION_LIST.get("Difluid Airwave command"), 0, "MODE EXT")
        self._add_row(alarms, 1, -1,-1, self.EVENTS.get("FC START"), 4.      , -3       , 2, 0.0, self.ACTION_LIST.get("TilauScope Ambient command"),   0,    "STOP"   )

        # 3. ALERTE DE DROP ESTIMÉE (ANTICIPATION)
        # Seuil BT ≈ 20 s avant la température de drop planifiée (au RoR de
        # drop du plan), armé après FC START. Remplace l'ancien popup statique
        # tiré à FC, qui n'anticipait rien.
        t_dev_sec = self._time_to_seconds(self.plan["Development Phase"])
        if t_dev_sec > 15:
            drop_temp = self._parse_val("Drop Temp")
            drop_ror  = self._parse_val("Target ROR at Drop")
            bt_margin = max(0.5, drop_ror * 20.0 / 60.0)   # °/20 s au RoR de drop
            self._add_row(alarms, 1, -1,-1, self.EVENTS.get("FC START"), 0.      , 1        , 1, round(drop_temp - bt_margin, 1), self.ACTION_LIST.get("PopUp"), 1,    "PREPARE TO DROP (~20 s)"   )
        
        # 4. DROP
        self._add_row(alarms, 1, -1,-1, self.EVENTS.get("DROP"), 0.      , -3       , 2, 0.0, self.ACTION_LIST.get("Slider Burner"),       0, "0")
        self._add_row(alarms, 1, -1,-1, self.EVENTS.get("DROP"), 1.      , -3       , 2, 0.0, self.ACTION_LIST.get("Slider Air"),      0, "50" )
        if drums[0] is not None:   # même gating tambour fixe qu'aux autres phases
            self._add_row(alarms, 1, -1,-1, self.EVENTS.get("DROP"), 2.      , -3       , 2, 0.0, self.ACTION_LIST.get("Slider Drum"),     0, "80" )
        if self._airwave_present:
            self._add_row(alarms, 1, -1,-1, self.EVENTS.get("DROP"), 3., -3, 2, 0.0, self.ACTION_LIST.get("Slider Damper"), 0, "80")

# should add cooling fan if any
        
        return alarms

    def _add_row(self, storage, status=1, ifalarm=-1, butnotalarm=-1, from_event=0, at_seconds=0, source=1, condition=1, condition_value=0.0, action=1, beep=0, msg="")->int:
        storage["alarmflags"].append(status)
        storage["alarmguards"].append(ifalarm)
        storage["alarmnegguards"].append(butnotalarm)
        storage["alarmtimes"].append(from_event)
        storage["alarmoffsets"].append(at_seconds)
        storage["alarmsources"].append(source) # -3=time, 1=BT, …
        storage["alarmconds"].append(condition) # 0 = falls below; 1 = rises above; 2 = equal
        storage["alarmtemperatures"].append(condition_value)
        storage["alarmactions"].append(action) # "Popup", "SV", etc.
        storage["alarmbeep"].append(beep)
        storage["alarmstrings"].append(msg)
        return len(storage["alarmflags"]) - 1   # row index, usable as (neg)guard

    def export(self, filename:str)->None:
        with open(filename, 'w') as f:
            json.dump(self.alarms, f, separators=(',', ':'))
            
class BuildPRoastPlanPDF(FPDF):
    """Custom FPDF class for the roast plan report."""
    def __init__(self, orientation="P", unit="mm", format="A4", temp_unit="C",
                 roaster_ctx: "RoasterContext | None" = None):
        super().__init__(orientation, unit, format)
        self.mode = temp_unit
        self._target = ""
        self._roaster = ""
        self._roaster_ctx: "RoasterContext | None" = roaster_ctx

    def _fmt_ctrl(self, raw: str, label_fn) -> str:
        """Enrich '75%' → '75% (1800 W)' when physical range is available."""
        try:
            return label_fn(float(raw.strip().replace('%', '')))
        except (ValueError, AttributeError):
            return raw
        
    def header(self)->None:
        self.set_font('helvetica', 'B', 15)
        self.cell(0, 10, QApplication.translate("tilauscope_roast_plan",'Automated Roast Profile Plan'), new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
        self.ln(2)
        self.set_font('helvetica', 'B', 12)
        self.cell(0, 10, f"({self._target})", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
        self.ln(3)

    def footer(self)->None:
        self.set_y(-15)
        self.set_font('helvetica', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()}', align='C')
     
    def draw_enhanced_roast_graph(self, master_data, x_pos, y_pos, width, height, bt_plan_curve=None):
        """
        Dual-axis roast graph:
          Left  Y-axis : ROR in °C/min  → scale_ror()   range [ROR_MIN .. ROR_MAX]
          Right Y-axis : BT  in °C      → scale_bt()    range [BT_MIN  .. BT_MAX ]
          Both axes share the same pixel rectangle (x_pos,y_pos,width,height) but
          each curve is mapped through its OWN scale function — they never mix.

        Layer order (bottom → top):
          A  Phase background bands
          B  ROR variance envelope (fill) + historical ROR mean (blue solid)
          C  Historical BT mean (dark red, dashed)
          D  Planned BT curve (orange solid) + planned ROR (orange dashed)
          E  Waypoint circles & labels on planned BT
          F  Grid lines + axis tick labels  (drawn last so grid is on top of fills)
          G  Graph border
          H  Legend below graph
        """
        # ── 0. TIME AXIS ────────────────────────────────────────────────────────
        T_MAX = master_data["time_min"][-1]
        if bt_plan_curve:
            T_MAX = max(T_MAX, bt_plan_curve["time_min"][-1])

        def scale_x(t: float) -> float:
            return x_pos + (t / T_MAX) * width

        ROR_MIN = 0.0
        ROR_MAX = 25.0 if self.mode == "C" else 25.0 * 1.8   # 45 °F/min ≈ 25 °C/min

        def scale_ror(r: float) -> float:
            """Maps a RoR value in native °/min to a PDF Y coordinate."""
            r_clamped = max(ROR_MIN, min(ROR_MAX, r))
            return y_pos + height - (r_clamped / ROR_MAX) * height

        # ── 2. BT AXIS   (right, BT_MIN … BT_MAX °C) ───────────────────────────
        # Compute dynamic BT range from ALL BT data (historical + planned).
        all_bt_values: list[float] = [
            v for v in master_data.get("bt_mean", [])
            if v is not None and not (isinstance(v, float) and np.isnan(v)) and v > 0
        ]
        if bt_plan_curve:
            all_bt_values += [
                v for v in bt_plan_curve["bt_plan"]
                if v is not None and v > 0
            ]

        if all_bt_values:
            BT_MIN = int(min(all_bt_values) // 10) * 10       # floor to decade
            BT_MAX = int((max(all_bt_values) // 10) + 1) * 10 # ceil  to decade
        else:
            BT_MIN = 60 if self.mode == "C" else (60 * 9/5) + 32
            BT_MAX = 240 if self.mode == "C" else (240 * 9/5) + 32

        # Safety: prevent degenerate scale
        if BT_MAX <= BT_MIN:
            BT_MIN = 60 if self.mode == "C" else (60 * 9/5) + 32
            BT_MAX = 240 if self.mode == "C" else (240 * 9/5) + 32

        def scale_bt(temp: float) -> float:
            """Maps a BT temperature (°C) to a PDF Y coordinate using the BT axis."""
            t_clamped = max(BT_MIN, min(BT_MAX, temp))
            return y_pos + height - ((t_clamped - BT_MIN) / (BT_MAX - BT_MIN)) * height

        # ── A. PHASE BACKGROUND BANDS ───────────────────────────────────────────
        phases = master_data.get("phase_times", {})
        phase_colors = {
            "DRY":         (255, 252, 230),
            "MAILLARD":    (255, 240, 210),
            "DEVELOPMENT": (245, 230, 220),
        }
        curr_t = 0
        plan_phases = {wp["label"]: wp["time_min"] * 60 for wp in bt_plan_curve.get("waypoints", [])} if bt_plan_curve else {}
        for phase_name, t_end_sec in [
            ("DRY",         plan_phases.get(QApplication.translate("Button", "DRY END"), phases.get("dry_end_sec", 300))),
            ("MAILLARD",    plan_phases.get(QApplication.translate("Button", "FC START"),      phases.get("fc_start_sec", 600))),
            ("DEVELOPMENT", int(T_MAX * 60)),
        ]:
            t_start_min = curr_t / 60.0
            t_end_min   = t_end_sec / 60.0
            band_x      = scale_x(t_start_min)
            band_w      = scale_x(t_end_min) - band_x
            self.set_fill_color(*phase_colors[phase_name])
            self.rect(band_x, y_pos, band_w, height, style="F")
            curr_t = t_end_sec

        # ── B. ROR VARIANCE ENVELOPE + HISTORICAL ROR MEAN ─────────────────────
        ror_times = master_data["time_min"]
        ror_min = master_data["ror_min"]
        ror_max = master_data["ror_max"]
        ror_mean  = master_data["ror_mean"]

        # Variance fill (light blue)
        # Check if we have data and if there is actually a difference to draw
       # Create the envelope path
        points = []
        # Forward for the top edge
        for i, val in enumerate(ror_max):
            points.append((scale_x(ror_times[i]), scale_ror(val)))
        for i in reversed(range(len(ror_min))):
            points.append((scale_x(ror_times[i]), scale_ror(ror_min[i])))
        self.set_fill_color(173, 216, 230)   # light blue — RGB for "light blue"
        self.set_draw_color(173, 216, 230)   # same, so the outline doesn't show a darker border
        self.polygon(points, style="F")
        
        # Historical ROR mean (solid blue, 0.6 pt)
        self.set_draw_color(0, 50, 150)
        self.set_line_width(0.6)
        self.set_dash_pattern()           # SOLID — reset any previous dash
        for i in range(len(ror_times) - 1):
            rc, rn = ror_mean[i], ror_mean[i+1]
            if rc is not None and rc > 0 and rn is not None and rn > 0:
                self.line(
                    scale_x(ror_times[i]),   scale_ror(rc),
                    scale_x(ror_times[i+1]), scale_ror(rn),
                )

        # ── C.1  BT VARIANCE ENVELOPE (light blue, BT axis) ──────────────────
        bt_times = master_data["time_min"]
        bt_mean  = master_data["bt_mean"]

        bt_min_data = master_data.get("bt_min")
        bt_max_data = master_data.get("bt_max")
        if bt_min_data and bt_max_data:
            self.set_fill_color(173, 216, 230)   # light blue
            self.set_draw_color(173, 216, 230)
            bt_points = []
            for i, val in enumerate(bt_max_data):
                if val is not None and not np.isnan(val):
                    bt_points.append((scale_x(bt_times[i]), scale_bt(val)))
            for i in reversed(range(len(bt_min_data))):
                val = bt_min_data[i]
                if val is not None and not np.isnan(val):
                    bt_points.append((scale_x(bt_times[i]), scale_bt(val)))
            if len(bt_points) > 2:
                self.polygon(bt_points, style="F")

        # ── C. HISTORICAL BT MEAN  (dark red solid, mapped on BT axis) ─────────

        self.set_draw_color(160, 0, 0)    # dark red — distinct from orange plan
        self.set_line_width(0.5)
        self.set_dash_pattern()
        for i in range(len(bt_times) - 1):
            bc, bn = bt_mean[i], bt_mean[i+1]
            if (bc is not None and not (isinstance(bc, float) and np.isnan(bc)) and bc > 0 and
                bn is not None and not (isinstance(bn, float) and np.isnan(bn)) and bn > 0):
                self.line(
                    scale_x(bt_times[i]),   scale_bt(bc),
                    scale_x(bt_times[i+1]), scale_bt(bn),
                )
        self.set_dash_pattern()           # RESET to solid

        # ── D. PLANNED BT CURVE + PLANNED ROR  (both orange, mapped on CORRECT axes)
        if bt_plan_curve:
            plan_times = bt_plan_curve["time_min"]
            plan_bt    = bt_plan_curve["bt_plan"]
            plan_ror   = bt_plan_curve["ror_plan"]
            STEP = 1   # subsample every 5 points (= 5 s) for PDF size

            # D.1  Planned BT — green 0.4 pt — uses scale_bt (RIGHT axis)
            self.set_draw_color(0, 160, 0)    # green 
            self.set_line_width(0.4)
            self.set_dash_pattern(dash=1.5, gap=1.0)
            bt_plan_points = []
            for i in range(0, len(plan_times) - STEP, STEP):
                bc = plan_bt[i]
                if bc is not None:
                    # Append as a tuple (x, y)
                    bt_plan_points.append((
                        scale_x(plan_times[i]), 
                        scale_bt(bc)
                    ))
            if len(bt_plan_points) > 1:
                self.polyline(bt_plan_points)

            # D.2  Planned ROR — dashed orange 0.4 pt — uses scale_ror (LEFT axis)
            self.set_draw_color(200, 120, 20)   # slightly lighter orange for ROR
            self.set_line_width(0.4)
            self.set_dash_pattern(dash=2.5, gap=1.5)
            ror_plan_points = []
            for i in range(0, len(ror_times), STEP):
                val = plan_ror[i] if i< len (plan_times) else None
                if val is not None:
                    # Append as a tuple (x, y)
                    ror_plan_points.append((
                        scale_x(plan_times[i]), 
                        scale_ror(val)
                    ))
            if len(ror_plan_points) > 1:
                self.polyline(ror_plan_points)
            
            self.set_dash_pattern()       # RESET

        # ── E. WAYPOINT ANNOTATIONS (Option 2: Leader Lines) ────────────────
        # Define a fixed 'lane' for labels 7mm above the graph grid top
        lane_high = y_pos - 10  # Higher lane
        lane_low = y_pos - 4   # Lower lane

        self.set_font("Helvetica", "B", 6)
        self.set_line_width(0.35)

        ANNOTATED = {QApplication.translate("Button","CHARGE"), QApplication.translate("Label","TP"), QApplication.translate("Button","DRY END"), QApplication.translate("Button","FC START"), QApplication.translate("Button","DROP")}
        # which labels go above the curve vs below
        ABOVE = {QApplication.translate("Button","CHARGE"), QApplication.translate("Button","FC START")}

        # Sort waypoints by time to ensure the alternating pattern is consistent
        active_waypoints = [wp for wp in bt_plan_curve["waypoints"] if wp["label"] in ANNOTATED]
        active_waypoints.sort(key=lambda x: x["time_min"])
        
        for i, wp in enumerate(active_waypoints):
            x_wp = scale_x(wp["time_min"])
            y_wp = scale_bt(wp["bt"])

            # Alternating height: 0=High, 1=Low
            # This prevents "CHARGE" and "TP" from crashing into each other
            current_lane_y = lane_high if i % 2 == 0 else lane_low

            # 1. Waypoint Marker
            self.set_draw_color(70, 160, 0)
            self.set_fill_color(255, 255, 255)
            self.set_line_width(0.5)
            self.ellipse(x_wp - 0.8, y_wp - 0.8, 1.6, 1.6, style="FD")

            # 2. Leader Line (adjusts length based on the chosen lane)
            self.set_draw_color(20, 20, 20)
            self.set_line_width(0.1)
            self.set_dash_pattern(dash=0.4, gap=0.4)
            self.line(x_wp, y_wp, x_wp, current_lane_y)
            self.set_dash_pattern() # Reset

            # 3. Text Label
            label_txt = f"{wp['label']}\n{wp['bt']:.1f}°{self.mode}"
            # Since it's multi-line, we calculate width based on the longest line
            title_w = self.get_string_width(wp['label'])
            value_w = self.get_string_width(f"{wp['bt']:.1f}°{self.mode}")
            text_w = max(title_w, value_w) + 2  # Added 2mm padding for safety
            
            # Position text relative to the leader line tip
            # If high lane, text goes above. If low lane, text sits right there.
            lx = x_wp - (text_w / 2)
            # Boundary check
            lx = max(x_pos, min(lx, x_pos + width - text_w))

            self.set_text_color(30, 30, 30)

            line_height = 3.0  # Height of a single line of text
            # multi_cell allows \n and handles the line wrapping
            # align='C' ensures both lines are centered relative to each other
            self.set_xy(lx, current_lane_y - (line_height * 2) - 1)
            self.multi_cell(
                w=text_w, 
                h=line_height, 
                txt=label_txt, 
                border=0, 
                align='C'
            )
        self.set_text_color(50, 50, 50)

        # ── F. GRID LINES + AXIS TICK LABELS ────────────────────────────────────
        self.set_draw_color(200, 200, 200)
        self.set_line_width(0.1)
        self.set_text_color(50, 50, 50)
        self.set_font("Helvetica", "", 7)

        # Vertical grid: one line per minute
        for m in range(0, int(T_MAX) + 1):
            xm = scale_x(float(m))
            self.line(xm, y_pos, xm, y_pos + height)
            self.text(xm - 2, y_pos + height + 5, f"{m}'")

        # Horizontal grid: ROR ticks on left axis (every 5 °C/min)
        for r in range(int(ROR_MIN), int(ROR_MAX) + 1, 5):
            yr = scale_ror(float(r))
            self.line(x_pos, yr, x_pos + width, yr)
            self.text(x_pos - 10, yr + 2, f"{r}")

        # BT tick labels on right axis (every 20 °C) — NO extra grid lines,
        # they would duplicate the ROR grid and create the confusing double-line look.
        for bt_tick in range(BT_MIN, BT_MAX + 1, 20):
            yt = scale_bt(float(bt_tick))
            # Only draw tick label if it falls inside the graph rectangle
            if y_pos <= yt <= y_pos + height:
                self.text(x_pos + width + 3, yt + 2, f"{bt_tick}°{self.mode}")

        # ── G. GRAPH BORDER ─────────────────────────────────────────────────────
        self.set_draw_color(100, 100, 100)
        self.set_line_width(0.3)
        self.rect(x_pos, y_pos, width, height, style="D")

        # Axis title labels
        self.set_font("Helvetica", "B", 7)
        self.text(
            x_pos - 15, y_pos - 5,
            QApplication.translate("Label", "RoR") +
            f" (°{self.mode}" +
            QApplication.translate("Label", "/min") + ")"
        )
        self.text(
            x_pos + width + 3, y_pos - 5,
            QApplication.translate("Label", "BT") + f": (°{self.mode})")
        self.text(
            x_pos + width / 2 - 5, y_pos + height + 12,
            QApplication.translate("tilauscope_roast_plan", "Time") + " (min)"
        )

        # ── H. LEGEND ────────────────────────────────────────────────────────────
        leg_y = y_pos + height + 20
        self.set_font("Helvetica", "", 8)

        # Row 1 ─ left half: historical ROR (blue solid) + variance box
        #         right half: historical BT (dark red dashed)
        self.set_draw_color(0, 50, 150)
        self.set_line_width(0.8)
        self.set_dash_pattern()
        self.line(x_pos, leg_y, x_pos + 10, leg_y)
        self.set_text_color(0, 0, 0)
        self.text(x_pos + 13, leg_y + 2.5,
                  QApplication.translate("Label", "RoR") +
                  QApplication.translate("tilauscope_roast_plan", " Average (hist.)"))

        self.set_fill_color(200, 220, 255)
        self.rect(x_pos + 58, leg_y - 2, 8, 5, style="F")
        self.set_draw_color(150, 170, 220)
        self.set_line_width(0.3)
        self.rect(x_pos + 58, leg_y - 2, 8, 5, style="D")
        self.set_text_color(0, 0, 0)
        self.text(x_pos + 68, leg_y + 2.5,
                  QApplication.translate("tilauscope_roast_plan", "RoR variance"))

        self.set_draw_color(0, 160, 0)
        self.set_line_width(0.4)
        self.set_dash_pattern(dash=1.5, gap=1.0)
        self.line(x_pos + 110, leg_y, x_pos + 120, leg_y)
        self.set_dash_pattern()
        self.set_text_color(0, 0, 0)
        self.text(x_pos + 123, leg_y + 2.5,
                  QApplication.translate("tilauscope_roast_plan", "BT Average (hist.)"))

        # Row 2 (only when plan curve exists) ─ planned BT solid + planned ROR dashed
        if bt_plan_curve:
            leg_y += 7
            self.set_draw_color(210, 100, 0)
            self.set_line_width(0.8)
            self.set_dash_pattern()
            self.line(x_pos, leg_y, x_pos + 10, leg_y)
            self.set_text_color(0, 0, 0)
            self.text(x_pos + 13, leg_y + 2.5,
                      QApplication.translate("tilauscope_roast_plan", "Planned BT (PCHIP)"))

            self.set_draw_color(200, 120, 20)
            self.set_line_width(0.4)
            self.set_dash_pattern(dash=2.5, gap=1.5)
            self.line(x_pos + 65, leg_y, x_pos + 75, leg_y)
            self.set_dash_pattern()
            self.set_text_color(0, 0, 0)
            self.text(x_pos + 78, leg_y + 2.5,
                      QApplication.translate("tilauscope_roast_plan", "Planned RoR"))

        # Row 3 ─ phase colour chips
        leg_y += 8
        self.set_font("Helvetica", "B", 7)
        self.set_text_color(0, 0, 0)

        self.set_fill_color(255, 252, 230)
        self.rect(x_pos, leg_y - 2, 4, 4, style="F")
        self.text(x_pos + 6, leg_y + 1,
                  QApplication.translate("tilauscope_roast_plan", "Drying (DRY)"))

        self.set_fill_color(255, 240, 210)
        self.rect(x_pos + 45, leg_y - 2, 4, 4, style="F")
        self.text(x_pos + 51, leg_y + 1,
                  QApplication.translate("Label", "Maillard"))

        self.set_fill_color(245, 230, 220)
        self.rect(x_pos + 85, leg_y - 2, 4, 4, style="F")
        self.text(x_pos + 91, leg_y + 1,
                  QApplication.translate("Label", "Development"))

    def ensure_space(self, needed_height:int):
        if self.get_y() + needed_height > self.page_break_trigger:
            self.add_page()

    def create_pdf_report(self, plan_data:dict, graph_data, crashes, flicks)->None:
        """Fills the PDF with the calculated roast plan data in a clear, structured format,
        including phase percentages."""

        self._target = plan_data["Target Roast Level"]
        self._roaster = plan_data["Roaster"]

        self.add_page()
        self.set_auto_page_break(auto=True, margin=15)

        # A4 vertical budget: with the header (~35 mm) the 4 sections + note
        # must stay under the 282 mm break trigger even with the two extra
        # AirWave rows — hence the 5.5 mm data rows and tight spacers below.
        _row_h = 5.5

        # just below the automatic header/title generated by the FPDF class's Header() method.
        self.ln(4)

        # 1. Bean & Ambient Information
        # Set up basic font 
        self.set_font('helvetica', '', 10) 
        
        # Set background color for section header
        self.set_fill_color(220, 220, 220) 
        self.set_font('helvetica', 'B', 12)
        self.cell(0, 7, QApplication.translate("tilauscope_roast_plan",'1. Bean and Environment Information'), new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True)
        self.ln(1)
        
        info_data = [
            (QApplication.translate("tilauscope_roast_plan","Roaster"), plan_data.get("Roaster")),
            (QApplication.translate("tilauscope_roast_plan","Bean Name"), plan_data.get("Bean Name")),
            (QApplication.translate("tilauscope_roast_plan","Process Type"), plan_data.get("Process Type")),
            (QApplication.translate("tilauscope_roast_plan","Density")+" (g/L)", plan_data.get("Density")),
            (QApplication.translate("tilauscope_roast_plan","Bean Humidity")+" (%)", plan_data.get("Bean Humidity")),
            (QApplication.translate("tilauscope_roast_plan","Ambient Temp")+f" (°{self.mode})", plan_data.get("Ambient Temp")),
            (QApplication.translate("tilauscope_roast_plan","Ambient Humidity")+" (%)", plan_data.get("Ambient Humidity")),
            (QApplication.translate("tilauscope_roast_plan","Weight to roast")+" (g)", plan_data.get("Weight")),
        ]
        
        self.set_font('helvetica', '', 10)
        for label, value in info_data:
            self.cell(80, _row_h, label + ':', border=0)
            self.cell(0, _row_h, str(value), new_x=XPos.LMARGIN, new_y=YPos.NEXT, border=0)

        # 2. Temperature & Timing Profile
        self.ln(2)
        self.set_fill_color(220, 220, 220)
        self.set_font('helvetica', 'B', 12)
        self.cell(0, 7, QApplication.translate("tilauscope_roast_plan",'2. Thermal Profile & Timing'), new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True)
        self.ln(1)

        # Helper function to combine Time and Phase % for presentation
        def get_phase_info(time_key:str, percent_key:str)->str:
            time = plan_data.get(time_key, "N/A")
            percent:str = plan_data.get(percent_key, "N/A")
            if percent != "N/A" and percent is not None:
                # Formatting to ensure the percentage has one decimal place, e.g., (35.4%)
                try:
                    percent_value = float(percent)
                    percent_str = f" ({percent_value:.1f}%)"
                except (ValueError, TypeError):
                    percent_str = f" ({percent}%)"
            else:
                percent_str = ""
                
            return f"{time}{percent_str}"

        profile_data = [
            (QApplication.translate("tilauscope_roast_plan","Charge Temp")+f" (°{self.mode})", plan_data.get("Charge Temp")), 
            (QApplication.translate("tilauscope_roast_plan","End of Dry Temp")+f" (°{self.mode})", plan_data.get("End of Dry Temp")),     
            (QApplication.translate("tilauscope_roast_plan","First Crack Temp")+f" (°{self.mode})", plan_data.get("First Crack Temp")),
            (QApplication.translate("tilauscope_roast_plan","First Crack source"), plan_data.get("FC Temp Source", "grid")),
            (QApplication.translate("tilauscope_roast_plan","Phase timing source"), plan_data.get("Phase Timing Source", "grid")),
            (QApplication.translate("tilauscope_roast_plan","Drop Temp")+f" (°{self.mode})", plan_data.get("Drop Temp")),
            (QApplication.translate("tilauscope_roast_plan","Drop RoR source"), plan_data.get("Drop ROR Source", "grid")),  ## TILAU ## item A         
            # --- PHASE TIME & % COMBINED ---
            (QApplication.translate("tilauscope_roast_plan","Dry Phase Time")+" (%)", get_phase_info("Dry Phase", "Dry Phase %")),           
            (QApplication.translate("tilauscope_roast_plan","Maillard Phase Time")+" (%)", get_phase_info("Maillard Phase", "Maillard Phase %")),         
            (QApplication.translate("tilauscope_roast_plan","Development Phase Time")+" (%)", get_phase_info("Development Phase", "Development Phase %")), # Assumes a key for Dev Phase Time/Duration
            # --- END OF PHASE TIME & % COMBINED ---
            (QApplication.translate("tilauscope_roast_plan","First Crack Time")+" ("+QApplication.translate("tilauscope_roast_plan","FC")+")", plan_data.get("FC Time")),    
            (QApplication.translate("tilauscope_roast_plan","Total Time")+" ("+QApplication.translate("tilauscope_roast_plan","Drop")+")", plan_data.get("Total Time")),             
        ]

        self.set_font('helvetica', '', 10)
        for label, value in profile_data:
            self.cell(80, _row_h, label + ':', border=0)
            self.cell(0, _row_h, str(value), new_x=XPos.LMARGIN, new_y=YPos.NEXT, border=0)

        # 3. Development Ratios (DTR) and Rates of Rise (RoR)
        self.ln(2)
        self.set_fill_color(220, 220, 220)
        self.set_font('helvetica', 'B', 12)
        self.cell(0, 7, QApplication.translate("tilauscope_roast_plan",'3. Development Ratios (DTR) and Rates of Rise (RoR)'), new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True)
        self.ln(1)

        ratio_data = [
            (QApplication.translate("tilauscope_roast_plan","Target Agtron Profile"), plan_data.get("Target Agtron")),
            (QApplication.translate("tilauscope_roast_plan","Plan confidence"), plan_data.get("Plan Confidence", "low (grid)")),
            (QApplication.translate("tilauscope_roast_plan","Resulting DTR (%)"), plan_data.get("Target DTR")),
            (QApplication.translate("tilauscope_roast_plan","Target ROR Maillard")+f" (°{self.mode}/min)", plan_data.get("Target ROR Maillard")),
            (QApplication.translate("tilauscope_roast_plan","Target ROR Dev")+" ("+QApplication.translate("tilauscope_roast_plan","Average")+f" °{self.mode}/min)", plan_data.get("Target ROR Dev (Avg)")), 
            (QApplication.translate("tilauscope_roast_plan","Target ROR at Drop")+f" (°{self.mode}/min)", plan_data.get("Target ROR at Drop")),
        ]

        self.set_font('helvetica', '', 10)
        for label, value in ratio_data:
            self.cell(80, _row_h, label + ':', border=0)
            self.cell(0, _row_h, str(value), new_x=XPos.LMARGIN, new_y=YPos.NEXT, border=0)

        # 4. Machine Controls (Table)
        self.ln(3)
        self.set_fill_color(220, 220, 220)
        self.set_font('helvetica', 'B', 12)
        self.cell(0, 7, QApplication.translate("tilauscope_roast_plan",'4. Machine Controls (Phases: Dry | Maillard | Development)'), new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True)
        self.ln(1)
        
        # Prepare Table Data - Keys match the output of generate_roast_plan
        _ctx = self._roaster_ctx
        _raw_drum   = plan_data.get("Drum Speed (%) (Dry|Mai|Dev)", "N/A | N/A | N/A").split(' | ')
        _raw_heater = plan_data.get("Heater (%) (Dry|Mai|Dev)",     "N/A | N/A | N/A").split(' | ')
        _raw_air    = plan_data.get("Airflow (%) (Dry|Mai|Dev)",    "N/A | N/A | N/A").split(' | ')

        if _ctx is not None:
            _raw_drum   = [self._fmt_ctrl(v, _ctx.pct_to_drum_label)    for v in _raw_drum]
            _raw_heater = [self._fmt_ctrl(v, _ctx.pct_to_heater_label)  for v in _raw_heater]
            _raw_air    = [self._fmt_ctrl(v, _ctx.pct_to_airflow_label) for v in _raw_air]

        controls = {
            QApplication.translate("tilauscope_roast_plan","Drum Speed")+" (%)": _raw_drum,
            QApplication.translate("tilauscope_roast_plan","Heater")+" (%)":     _raw_heater,
            QApplication.translate("tilauscope_roast_plan","Airflow")+" (%)":    _raw_air,
        }
        # AirWave (extraction) rows only when an AirWave was detected at plan time.
        _ext = plan_data.get("Extraction (%) (Dry|Mai|Dev)", "").strip()
        if _ext:
            controls[QApplication.translate("tilauscope_roast_plan","AirWave")+" (% "+QApplication.translate("tilauscope_roast_plan","Fan")+")"] = _ext.split(' | ')
        _awm = plan_data.get("AirWave Mode (Dry|Mai|Dev)", "").strip()
        if _awm:
            controls[QApplication.translate("tilauscope_roast_plan","AirWave Mode")] = _awm.split(' | ')
        
        col_widths = [42, 38, 38, 42]
        
        # Table Header
        self.set_font('helvetica', 'B', 10)
        self.cell(col_widths[0], 7, QApplication.translate("tilauscope_roast_plan","Control"), 1, align='C', fill=True)
        self.cell(col_widths[1], 7, QApplication.translate("Label","Dry"), 1, align='C', fill=True)
        self.cell(col_widths[2], 7, QApplication.translate("Label","Maillard"), 1, align='C', fill=True)
        self.cell(col_widths[3], 7, QApplication.translate("Label","Development"), 1, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C', fill=True)
        
        # Table Rows
        self.set_font('helvetica', '', 10)
        for label, values in controls.items():
            # Ensure there are 3 values, pad with 'N/A' if needed
            v = (values + ['N/A', 'N/A', 'N/A'])[:3]
            self.cell(col_widths[0], _row_h, label, 1)
            self.cell(col_widths[1], _row_h, v[0], 1, align='C')
            self.cell(col_widths[2], _row_h, v[1], 1, align='C')
            self.cell(col_widths[3], _row_h, v[2], 1, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')

        # Anticipated heater ramp (BT-triggered steps between Maillard and FC)
        _ramp = plan_data.get("Heater Ramp") or []
        if _ramp:
            self.ln(2)
            self.set_font('helvetica', '', 10)
            _ramp_str = "  ->  ".join(
                f"{e['heater']:.0f}% @ {e['bt']:.0f} °{self.mode}" for e in _ramp)
            _lead = plan_data.get("FC Anticipation (s)", "")
            if _lead:
                _ramp_str += "  (" + QApplication.translate("tilauscope_roast_plan", "last step {0} s before FC").format(_lead) + ")"
            ## TILAU ## bug fix : la chaîne de rampe (jusqu'à ~10 paliers) débordait
            ## de la marge droite et du bas de page dans un cell() mono-ligne ;
            ## multi_cell replie sur la largeur restante et laisse fpdf gérer le
            ## saut de page.
            self.cell(80, _row_h, QApplication.translate("tilauscope_roast_plan", "Heater ramp (anticipated)") + ':', border=0)
            self.multi_cell(0, _row_h, _ramp_str, new_x=XPos.LMARGIN, new_y=YPos.NEXT, border=0)

        # Heater provenance (learned from matched history vs grid) — same
        # "source" disclosure as First Crack / phase timing in section 2.
        _hsrc = plan_data.get("Heater Source", "grid")
        ## TILAU ## item C : provenance du palier pre-FC (feu au FC appris) —
        ## seulement affichée quand elle vient de l'historique (sinon = calcul
        ## du plan, l'info « grid » du heater principal suffit).
        _hfc = str(plan_data.get("Heater FC Source", "grid"))
        if _hfc != "grid":
            _hsrc = f"{_hsrc}  |  pre-FC: {_hfc}"
        self.set_font('helvetica', '', 10)
        self.cell(80, _row_h, QApplication.translate("tilauscope_roast_plan", "Heater source") + ':', border=0)
        self.multi_cell(0, _row_h, str(_hsrc), new_x=XPos.LMARGIN, new_y=YPos.NEXT, border=0)

        self.ln(3)
        self.set_font('helvetica', 'I', 9)
        self.multi_cell(0, 4, 
                        QApplication.translate("tilauscope_roast_plan","Note: The plan is generated for a Target Agtron profile of ")+
                        f"{plan_data.get('Target Agtron', 'N/A')} (Resulting DTR: {plan_data.get('Target DTR', 'N/A')}). "+
                        QApplication.translate("tilauscope_roast_plan","All temperatures are in BT (Bean Temperature) and times in Minutes:Seconds."), 
                        border=0)
        
        # 5. Historical Feedback (Notes and Actions)
        notes = plan_data.get("notes", [])
        actions = plan_data.get("actions", [])
        
        if notes is not None and len(notes)>0:
            self.add_page(same=True)
            try:
                self.set_fill_color(220, 220, 220)
                self.set_font('helvetica', 'B', 12)
                self.cell(0, 7, QApplication.translate("tilauscope_roast_plan",'5. Historical Feedback & Actions'), new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True)
                self.ln(2)

                # Standard loop for lists of strings
                for i in range(len(notes)):
                    # Warning Note
                    self.ensure_space(12)
                    self.set_font('helvetica', 'B', 10)
                    self.set_text_color(200, 0, 0) # Red for warnings
                    self.cell(0, 6, f"{notes[i]}",new_x=XPos.LMARGIN, new_y=YPos.NEXT,)
                    
                    # Associated Action
                    if i < len(actions):
                        self.ensure_space(12)
                        self.set_font('helvetica', 'I', 10)
                        self.set_text_color(0, 0, 0) # Back to black
                        self.cell(0, 6, f"{actions[i]}",new_x=XPos.LMARGIN, new_y=YPos.NEXT,)
                    
                    self.ln(2) 
                    
        # Reset text color for any following content
                self.set_text_color(0, 0, 0)
            except Exception as e:
                _logd.error(f"error printing pdf : {e}")

        # --- APPEL DU NOUVEAU GRAPHIQUE ---
        if graph_data:
            self.add_page()
            self.set_font("helvetica", "B", 14)
            self.cell(0, 10, QApplication.translate("tilauscope_roast_plan", "Historical Profile vs. Calculated Plan"), align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.ln(5)            
            self.ensure_space(80) # S'assure qu'il y a de la place pour le graph
            
            # Positionnement du graphique
            x_graph = self.get_x() + 10
            y_graph = self.get_y() + 20
            
            # Appel de la méthode améliorée (A, B, C)
            self.draw_enhanced_roast_graph(
                master_data   = graph_data, 
                x_pos         = x_graph, 
                y_pos         = y_graph, 
                width         = 160, 
                height        = 70,
                bt_plan_curve = plan_data.get("bt_plan_curve"),  # PCHIP planned curve
            )
            
            # On déplace le curseur après le graphique pour la suite (notes)
            self.set_y(y_graph + 85)            

class InjectRoastPlanToArtisan:
    """
    Injects information from a generated roast plan into an Artisan .alog structure.
    Includes timeindex mapping and mirrors slider changes as special events.
    """

    def __init__(self, plan_data: dict[str, Any], mode: str = "C"):
        # This is self.last_roast_plan_generated (data | precog)
        self.rp = plan_data
        # mode: Artisan display unit — plan temps are native, so the alog must
        # declare the same unit, and the missing-key fallbacks (°C doctrine)
        # must be converted.
        self.mode = mode if mode in ("C", "F") else "C"
        self.alog: dict[str, Any] = self._initialize_alog_template()

    def _parse_time(self, time_val: Any) -> float:
        """Parses 'mm:ss' string format or numeric value into total seconds."""
        try:
            ts = str(time_val).strip()
            if ":" in ts:
                minutes, seconds = map(int, ts.split(':'))
                return float(minutes * 60 + seconds)
            return float(ts or 0)
        except (ValueError, TypeError):
            _logd.warning(f"Invalid time format: {time_val}")
            return 0.0

    def _uncompact_values(self, val_str: Any) -> list[float]:
        """Converts '70% | 60% | 50%' into [70.0, 60.0, 50.0]."""
        if not isinstance(val_str, str):
            return []
        try:
            # Split by '|', remove '%', and convert to float
            return [float(v.replace('%', '').strip()) for v in val_str.split('|')]
        except (ValueError, AttributeError):
            return []
        
    def _initialize_alog_template(self) -> dict[str, Any]:
        """Initializes the Artisan alog structure based on hibean logic."""
        return {
            "recording_version": "3.2.1",
            "version": "3.2.1",
            "title": self.rp.get("name", "Roast Plan"),
            "mode": self.mode,
            "beans": "",
            "weight": [0.0, 0.0, "g"],
            "density": [0, "g", 1.0, "l"],
            "phases": [0, 0, 0, 0],    # [Charge, Dry End, FC Start, Drop]
            # Artisan timeindex is 8 entries: [CHARGE, DRYe, FCs, FCe, SCs, SCe, DROP, COOL]
            # index 0 sentinel = -1 (unmarked); indices 1..7 sentinel = 0 (unmarked).
            "timeindex": [-1, 0, 0, 0, 0, 0, 0, 0],
            "specialevents": [],       # Timestamps
            "specialeventstype": [],   # etype index
            "specialeventsvalue": [],  # value
            "specialeventsStrings": [],# label
            "etypes": [
                QApplication.translate('ComboBox', 'Air'),    # 0
                QApplication.translate('ComboBox', 'Drum'),   # 1
                QApplication.translate('ComboBox', 'Damper'), # 2
                QApplication.translate('ComboBox', 'Burner'), # 3
                '--'
            ],
            "timex": [0.0]*4,
            "temp1": [0.0]*4, # ET
            "temp2": [0.0]*4, # BT
            "computed": {}
        }

    def inject(self) -> dict[str, Any]:
        """Maps plan data and precog events into the Artisan structure."""
        try:
            # 1. Parse Phase Durations (mm:ss strings)
            d_sec = self._parse_time(self.rp.get('Dry Phase', '00:00'))
            m_sec = self._parse_time(self.rp.get('Maillard Phase', '00:00'))
            v_sec = self._parse_time(self.rp.get('Development Phase', '00:00'))

            # Cumulative timestamps (absolute seconds)
            t0 = 0.0
            t1 = d_sec
            t2 = d_sec + m_sec
            t3 = d_sec + m_sec + v_sec

            t_marks = [0.0, d_sec, d_sec + m_sec]
            drop_time_sec = d_sec + m_sec + v_sec  # genuine seconds here (from _parse_time)
            
            # Map event positions into timeindex
            # 0: Charge, 1: Dry End, 2: FC Start, 6: Drop
            self.alog["timeindex"][0] = 0
            self.alog["timeindex"][1] = 1
            self.alog["timeindex"][2] = 2
            self.alog["timeindex"][6] = 3
            self.alog["timex"][0] = 0
            self.alog["timex"][1] = t1
            self.alog["timex"][2] = t2
            self.alog["timex"][3] = t3
            def _safe_temp(key: str, default: float = 0.0) -> float:
                try:
                    return float(self.rp.get(key) or default)
                except (TypeError, ValueError):
                    _logd.warning(f"InjectRoastPlan: invalid value for '{key}', using {default}")
                    return default

            # fallback defaults are °C doctrine — express them in the alog unit
            _c2n = (lambda v: v * 9.0 / 5.0 + 32.0) if self.mode == "F" else (lambda v: v)
            self.alog["temp2"][0] = _safe_temp("Charge Temp",    _c2n(185.0))
            self.alog["temp2"][1] = _safe_temp("End of Dry Temp", _c2n(160.0))
            self.alog["temp2"][2] = _safe_temp("First Crack Temp",_c2n(196.0))
            self.alog["temp2"][3] = _safe_temp("Drop Temp",       _c2n(210.0))
            
            # Update legacy phases array
            self.alog["phases"] = [0, int(t1), int(t2), int(t3)]

            # 3. Special Events (Slider Changes)
            marks = [t0, t1, t2]
            slider_map = {
                "Airflow (%) (Dry|Mai|Dev)": 0,
                "Drum Speed (%) (Dry|Mai|Dev)": 1,
                "Extraction (%) (Dry|Mai|Dev)": 2,
                "Heater (%) (Dry|Mai|Dev)": 3
            }

            last_vals = {}

            for phase_idx in range(3):
                current_time = t_marks[phase_idx]

                for key, etype_idx in slider_map.items():
                    raw_val = self.rp.get(key, "")
                    values = self._uncompact_values(raw_val)
                    
                    if len(values) > phase_idx:
                        val = values[phase_idx]
                        
                        # Only record if it's the start (Charge) or the value changed
                        if etype_idx not in last_vals or val != last_vals[etype_idx]:
                            self.alog["specialevents"].append(round(current_time, 1))
                            self.alog["specialeventstype"].append(etype_idx)
                            self.alog["specialeventsvalue"].append(val)
                            self.alog["specialeventsStrings"].append(self.alog["etypes"][etype_idx])
                            last_vals[etype_idx] = val

            # 4. Target Temperatures (extracted from lists/floats)
            self.alog["computed"].update({
                "CHARGE_BT": round(_safe_temp("Charge Temp",    _c2n(185.0)), 1),
                "DRY_BT":    round(_safe_temp("End of Dry Temp", _c2n(160.0)), 1),
                "FC_BT":     round(_safe_temp("First Crack Temp",_c2n(196.0)), 1),
                "DROP_BT":   round(_safe_temp("Drop Temp",       _c2n(210.0)), 1),
            })
            
            return self.alog

        except Exception as e:
            _logd.error(f"Artisan injection failed: {e}")
            return self.alog
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
# TiLau 2025 — Adaptive Learning Extension

"""
tilaupid_adaptive.py
====================
Module d'apprentissage adaptatif pour TilauPreheatPID.

Fonctionnement :
  1. AlogScanner   — Scanne le répertoire des alogs Artisan et extrait les
                     métriques de torréfaction pertinentes (montée RoR,
                     dépassement, temps de stabilisation, conditions ambiantes).
  2. AdaptiveMemory — Stocke et agrège les métriques sur une fenêtre glissante
                      de N torréfactions (défaut 10).
  3. AmbientCorrector — Applique une correction multiplicative de puissance
                        basée sur T°/humidité/pression ambiantes.
  4. StabilisationDetector — Détecte en temps réel si le hold est stable
                             (variance glissante < seuil).
  5. AdaptivePIDMixin — Mixin à intégrer dans TilauPreheatPID ; expose
                        apply_adaptive_corrections() à appeler depuis
                        _precompute_targets() et cycle().

Intégration minimale dans tilaupid.py :
  • Importer AdaptivePIDMixin
  • Ajouter AdaptivePIDMixin comme base de TilauPreheatPID
  • Appeler self._adaptive_init() dans __init__
  • Appeler self._on_cycle_end(t_c, burner) depuis cycle()
  • Appeler self._on_preheat_complete() quand stabilisation détectée
"""

# Lazy annotations so this module can be imported by an offline corpus
# analysis tool WITHOUT importing artisanlib.main (which would bind a QApplication
# and clobber the user's real Artisan prefs). ApplicationWindow / ProfileData are
# used only in type hints + a string cast, so they live under TYPE_CHECKING.
from __future__ import annotations

import logging
import threading
import time
import math
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, median, stdev
from typing import List, Optional, Callable, TYPE_CHECKING
import ast  # Import de la bibliothèque ast
from typing import cast, Final

# Pure event-value conversion (internal→external %). Lives in artisanlib.util,
# which is safe to import at runtime (no QApplication, no prefs binding) — unlike
# artisanlib.main. This lets the alog scanner extract hold power WITHOUT an aw handle,
# so the offline corpus tool gets the same numbers as the live PID.
from artisanlib.util import events_internal_to_external_value, fromFtoCstrict
from tilauscope.tilaupid_thermal import (
    THERMAL_MODEL_FILENAME,
    ThermalModelCandidate,
    ThermalPromotionState,
    ThermalShadowResult,
    ThermalShadowSession,
    load_candidate,
)

if TYPE_CHECKING:
    from typing import Protocol

    from artisanlib.atypes import ProfileData
    from artisanlib.main import ApplicationWindow

    class _PIDConfigLike(Protocol):
        target_sv: float
        p_ss_default: float
        lead_sec_default: float
        lead_sec_min: float
        lead_sec_max: float
        max_burner: float

from PyQt6.QtCore import QSettings

_logd: Final[logging.Logger] = logging.getLogger("tilau")


def _normalise_identity(value: object) -> str:
    """Stable comparison/key form for machine labels stored by Artisan."""
    return "".join(ch for ch in str(value or "").casefold() if ch.isalnum())


def _robust_centre(values: list[float]) -> float:
    """Median for short series, 10% trimmed mean once the sample is long enough."""
    if not values:
        return 0.0
    ordered = sorted(float(v) for v in values)
    if len(ordered) < 10:
        return float(median(ordered))
    trim = max(1, int(len(ordered) * 0.10))
    core = ordered[trim:-trim]
    return float(mean(core or ordered))


def _robust_peak(values: list[float]) -> float:
    """Nearest-rank 95th percentile, avoiding one-sample sensor spikes."""
    if not values:
        return 0.0
    ordered = sorted(float(v) for v in values)
    idx = max(0, min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1))
    return ordered[idx]

# ─────────────────────────────────────────────────────────────────────────────
# Structures de données
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AmbientConditions:
    """Conditions ambiantes au moment du démarrage de la torréfaction."""
    temp_ambient: float = 20.0      # °C
    humidity: float = 50.0          # %RH
    pressure: float = 1013.25       # hPa

    def is_valid(self) -> bool:
        return ( self.temp_ambient is not None and self.humidity is not None and self.pressure is not None and (
            -10 < self.temp_ambient < 50
            and 0 < self.humidity < 100
            and 800 < self.pressure < 1100
        ))


@dataclass
class RoastPreheatMetrics:
    """
    Métriques extraites d'une torréfaction passée durant la phase de préchauffe.
    Toutes les températures sont en °C, les RoR en °C/min.
    """
    timestamp: float = 0.0              # epoch UNIX du début
    target_sv: float = 200.0            # consigne visée (°C)
    ambient: AmbientConditions = field(default_factory=AmbientConditions)

    # Montée
    mean_ramp_ror: float = 0.0          # RoR moyen pendant la rampe (°C/min)
    peak_ramp_ror: float = 0.0          # RoR max atteint

    # Approche
    overshoot_c: float = 0.0            # dépassement observé (°C, 0 si aucun)
    undershoot_c: float = 0.0           # sous-dépassement (si jamais atteint)
    time_to_sv_sec: float = 0.0         # secondes du START jusqu'à T = SV ± 2°C

    # Stabilisation
    stabilise_time_sec: float = 0.0     # secondes supplémentaires pour ±0.5°C
    hold_mean_power: float = 0.0        # puissance brûleur moyenne en hold (%)
    was_stable: bool = False            # True si stabilisation réelle détectée
    # True when target_sv came from a real recorded SV event ("TilauPID Preheat started");
    # extraction requires that marker, so every extracted metric sets this True.
    target_is_recorded_sv: bool = False
    # True when this roast logged the continuous 'Burner' extra-device channel — the only
    # trustworthy hold-power source. Historical roasts without it carry no P_ss datapoint.
    had_burner_channel: bool = False

    # Paramètres PID qui ont produit ce résultat
    zone_fuzzy_start_used: float = 0.87
    coast_lookahead_sec_used: float = 6.0
    max_burner_used: float = 85.0
    base_hold_power_used: float = 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Thermal Model Weighting Kernels
# ─────────────────────────────────────────────────────────────────────────────

def weight_triangular(roast_sv: float, roast_ambient: 'AmbientConditions',
                      target_sv: float, current_ambient: 'AmbientConditions') -> float:
    """
    Triangular kernel: linear decay to zero at window edge.

    Used for FIR roasters (fast response): Skywalker, Kaleido, Cyberroaster.
    Windows: ±10°C (SV), ±10°C (temp), ±10% (humidity), ±50 hPa (pressure).
    """
    w_sv = max(0.0, 1.0 - abs(roast_sv - target_sv) / 10.0)
    w_temp = max(0.0, 1.0 - abs(roast_ambient.temp_ambient - current_ambient.temp_ambient) / 10.0)
    w_hum = max(0.0, 1.0 - abs(roast_ambient.humidity - current_ambient.humidity) / 10.0)
    w_pres = max(0.0, 1.0 - abs(roast_ambient.pressure - current_ambient.pressure) / 50.0)
    return w_sv * w_temp * w_hum * w_pres


def weight_gaussian(roast_sv: float, roast_ambient: 'AmbientConditions',
                    target_sv: float, current_ambient: 'AmbientConditions',
                    sigma: float = 1.0) -> float:
    """
    Gaussian kernel: smooth decay, never zero.

    Used for convection/induction roasters (thermal inertia): Bullet, Roest, Behmor.
    Gives soft weight even to distant conditions, better for inertial systems.

    sigma: standard deviation of the Gaussian (typical: 0.8–1.2)
    """
    # Normalize distances
    d_sv = (roast_sv - target_sv) / 10.0
    d_temp = (roast_ambient.temp_ambient - current_ambient.temp_ambient) / 10.0
    d_hum = (roast_ambient.humidity - current_ambient.humidity) / 10.0
    d_pres = (roast_ambient.pressure - current_ambient.pressure) / 50.0

    # Euclidean distance squared
    dist_sq = d_sv**2 + d_temp**2 + d_hum**2 + d_pres**2

    # Gaussian kernel
    return math.exp(-dist_sq / (2 * sigma**2))


# ─────────────────────────────────────────────────────────────────────────────
# 1. AlogScanner
# ─────────────────────────────────────────────────────────────────────────────

class AlogScanner:
    """
    Scanne le répertoire des fichiers alog Artisan et extrait les métriques
    de préchauffe.  Les alogs sont des fichiers JSON produits par Artisan.

    """

    ALOG_GLOB = "*.alog"

    ## Combien de profils on accepte d'OUVRIR quand les torréfactions
    ## exploitables se font rares. Distinct de `window`, qui reste la
    ## profondeur de mémoire ET le dénominateur de confiance.
    _SCAN_BUDGET_MIN: Final[int] = 50
    _SCAN_BUDGET_FACTOR: Final[int] = 5

    def __init__(self, alog_dir: str, window: int = 10, aw:ApplicationWindow | None = None,
                 scan_budget: int | None = None):
        self.alog_dir = Path(alog_dir)
        self.window = window
        ## La lecture d'un profil ne coûte plus le parcours du corpus : le
        ## portillon sur index écarte gratuitement ce qui n'est pas une preuve
        ## PID. On peut donc chercher plus loin que `window` quand il le faut.
        self.scan_budget = (scan_budget if scan_budget is not None
                            else max(self._SCAN_BUDGET_MIN, window * self._SCAN_BUDGET_FACTOR))
        self.aw = aw
        qmc = getattr(aw, "qmc", None)
        machine = (
            getattr(qmc, "roastertype_setup", "")
            or getattr(qmc, "roastertype", "")
            or getattr(qmc, "machinesetup", "")
        )
        self.machine_fingerprint = _normalise_identity(machine)
        source = getattr(getattr(aw, "pidcontrol", None), "pidSource", None)
        self.control_channel = self._control_channel(source) if source is not None else None

    @staticmethod
    def _control_channel(pid_source: object) -> str:
        try:
            if not isinstance(pid_source, (str, bytes, bytearray, int, float)):
                return "BT"
            return "BT" if int(pid_source) in (0, 1) else "ET"
        except (TypeError, ValueError):
            return "BT"

    def _list_recent(self) -> List[Path]:
        """Return at most ``scan_budget`` index-qualified alogs, newest-first.

        ``scan_budget`` is a hard I/O ceiling, not a target number of eligible
        profiles: without one, an archive full of unrelated roasts would have
        the preheat parse everything while looking for its ten hits.

        Two things make a deeper look affordable now. The corpus index rules out
        a simulated profile, another machine, the other probe or an implausible
        ambient reading without opening anything — so the ceiling is only spent
        on plausible candidates. And ``load_window`` stops the moment it holds
        ``window`` usable roasts, so the full budget is paid only when the
        evidence really is scarce, which is exactly when looking harder pays.

        ``window`` deliberately stays what it was: how many roasts the adaptive
        memory keeps, and the denominator of its confidence. Raising it to widen
        the search would have DILUTED the learning — every correction is scaled
        by n/window, so finding six roasts in a window of thirty weighs less
        than three in a window of ten.
        """
        if not self.alog_dir.exists():
            _logd.warning(f"Répertoire alog introuvable : {self.alog_dir}")
            return []
        files = sorted(
            self.alog_dir.glob(self.ALOG_GLOB),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )
        eligible = [f for f in files if self._index_admits(f)]
        if len(eligible) < len(files):
            _logd.debug(
                f"AlogScanner: {len(files) - len(eligible)} profil(s) écartés sur index "
                f"(simulé / autre machine / autre voie / ambiant) avant toute lecture")
        return eligible[:max(0, self.scan_budget)]

    def _index_admits(self, path: Path) -> bool:
        """False only when the index PROVES this roast is not PID evidence.

        Unknown to the index — or an index that cannot be read — means keep:
        the full extraction below stays the authority, so a stale index can
        only cost reads, never silently narrow what the PID learns from.
        """
        try:
            from tilauscope.alogmanager import AlogIndex
            meta = AlogIndex.instance().records(self.alog_dir).get(str(path))
        except Exception:  # noqa: BLE001
            return True
        if meta is None:
            return True
        # Simulator data is never physical PID evidence. `tilau_exclude_learning`
        # is deliberately NOT tested: it vetoes cooking/roast-plan learning only,
        # not the independent machine preheat response.
        if meta.simulated:
            return False
        if self.machine_fingerprint:
            recorded = _normalise_identity(meta.roastertype or meta.machinesetup)
            if recorded != self.machine_fingerprint:
                return False
        if self.control_channel is not None:
            if self._control_channel(meta.pid_source) != self.control_channel:
                return False
        # Ambient plausibility — the single reason nearly every archived roast is
        # turned away. Reading it from the index means the ten-file budget goes to
        # roasts that can actually teach the PID something, instead of being
        # spent discovering that a probe was not connected.
        temp = meta.ambient_temp
        if str(meta.mode).upper() == "F":
            temp = fromFtoCstrict(temp)
        if not AmbientConditions(temp_ambient=temp, humidity=meta.ambient_humidity,
                                 pressure=meta.ambient_pressure).is_valid():
            return False
        return True

    def _extract_metrics(self, path: Path, params:RoastPreheatMetrics|None = None) -> RoastPreheatMetrics|None:
        """Parse un alog et retourne les métriques de préchauffe, ou None si absent."""
        try:
            # An .alog is a repr()'d Python dict — feed it straight to literal_eval,
            # which handles \uXXXX / \n escapes natively (unlike codecs.decode).
            try:
                text = path.read_text(encoding='utf-8')
            except UnicodeDecodeError:
                text = path.read_bytes().decode('latin-1')
            data = cast('ProfileData', ast.literal_eval(text))
        except Exception as exc:
            _logd.debug(f"Impossible de lire {path.name}: {exc}")
            return None

        # Simulator data is never physical PID evidence. Conversely,
        # `tilau_exclude_learning` belongs to roast-plan/cooking learning only:
        # it must not discard the independent machine preheat response.
        if isinstance(data, dict) and data.get('tilau_simulated'):
            _logd.debug(f"{path.name}: profil simulé — ignoré pour l'apprentissage PID")
            return None

        recorded_machine = _normalise_identity(
            data.get("roastertype") or data.get("machinesetup"))
        if self.machine_fingerprint and recorded_machine != self.machine_fingerprint:
            _logd.debug(
                f"{path.name}: machine {recorded_machine or 'absente'} != "
                f"{self.machine_fingerprint} — apprentissage PID ignoré")
            return None

        pid_source = data.get("pidSource", 1)
        recorded_channel = self._control_channel(pid_source)
        if self.control_channel is not None and recorded_channel != self.control_channel:
            _logd.debug(
                f"{path.name}: source {recorded_channel} != {self.control_channel} "
                "— apprentissage PID ignoré")
            return None

        if params is None:
            params = RoastPreheatMetrics()

        mode = str(data.get("mode", "C")).upper()
        # ── Conditions ambiantes ──────────────────────────────────────────
        try:
            ambient_temp = float(data.get("ambientTemp", 20.0))
            if mode == "F":
                ambient_temp = fromFtoCstrict(ambient_temp)
            ambient = AmbientConditions(
                temp_ambient=ambient_temp,
                humidity=float(data.get("ambient_humidity", 50.0)),
                pressure=float(data.get("ambient_pressure", 1013.25)),
            )
        except (TypeError, ValueError):
            return None
        if not ambient.is_valid():
            _logd.debug(f"{path.name}: conditions ambiantes invalides — apprentissage PID ignoré")
            return None

        # ── Série temporelle ─────────────────────────────────────────────
        timex: List[float] = data.get("timex", [])
        timeindex: List[int] = data.get("timeindex", [])
        # Channel the preheat PID actually followed in this roast — mirrors cycle():
        # BT=temp2 when pidSource in {0,1}, else ET=temp1 (Artisan convention: temp1=ET, temp2=BT).
        ctrl_raw: List[float] = data.get("temp2", []) if recorded_channel == "BT" else data.get("temp1", [])
        charge:int = timeindex[0] if (timeindex and timeindex[0] >= 0 ) else len(timex)-1 # charge index into timex

        # An .alog is stored in the unit it was recorded in (data['mode']); all PID/seed
        # maths is in °C, so an °F-recorded roast must be converted here.
        # target_sv is resolved later from the preheat window, not from svValues
        # (Artisan's preset-BUTTON array, not a time series).
        if mode == "F":
            # Convert real readings only; preserve Artisan's -1 dropped-sample sentinel.
            ctrl_temp: List[float] = [v if v == -1 else fromFtoCstrict(v) for v in ctrl_raw]
        else:
            ctrl_temp = ctrl_raw

        if len(timex) < 10 or len(ctrl_temp) < 10:
            return None  # pas assez de données

        preheat_start_idx = None
        preheat_end_idx = None

        # A guided TilauPID preheat is proven by `tilau_preheat_sv_c` (primary, SV in °C)
        # or the type-4 "TilauPID Preheat started" event — never by alarm strings. Neither present
        # ⇒ preheat was done by hand: not a valid learning base, skip.
        key_sv_c = data.get("tilau_preheat_sv_c")
        found_in_events = False
        recorded_sv_native: Optional[float] = None
        events_type = data.get("specialeventstype", [])
        events_strings = data.get("specialeventsStrings", [])
        events_value = data.get("specialeventsvalue", [])
        events_timex = data.get("specialevents", [])

        for k, ev in enumerate(events_type):
            if (ev == 4
                    and k < len(events_strings)
                    and k < len(events_timex)
                    and k < len(events_value)
                    and events_strings[k] == "TilauPID Preheat started"):
                preheat_start_idx = events_timex[k]
                preheat_end_idx = charge
                # Decode the intended SV (native unit) exactly like the type-3 hold reads.
                recorded_sv_native = float(events_internal_to_external_value(events_value[k]))
                found_in_events = True
                break

        if key_sv_c is None and not found_in_events:
            return None

        # Key-only file (no event): the preheat is the whole pre-CHARGE window.
        if not found_in_events:
            preheat_start_idx = 0
            preheat_end_idx = charge

        # ── Extraction des sous-séquences ────────────────────────────────
        if (not isinstance(preheat_start_idx, int)
                or not isinstance(preheat_end_idx, int)):
            return None
        i0, i1 = preheat_start_idx, preheat_end_idx
        if i0 < 0 or i1 < i0 or i1 >= min(len(timex), len(ctrl_temp)):
            return None
        t_slice = timex[i0: i1 + 1]
        ctrl_slice = ctrl_temp[i0: i1 + 1]

        if len(t_slice) < 3:
            return None

        # ── Cible (target_sv, °C) ─────────────────────────────────────────
        # Prefer the explicit °C key (exact, already internal-unit); fall back to
        # the event's native value converted via mode. Either way it is the real dialed
        # setpoint, so overshoot (max_bt − SV) and the exact-SV P_ss node are meaningful.
        try:
            if key_sv_c is not None:
                target_sv = float(key_sv_c)
            elif recorded_sv_native is not None:
                target_sv = (
                    fromFtoCstrict(recorded_sv_native)
                    if mode == "F" else float(recorded_sv_native)
                )
            else:
                return None
        except (TypeError, ValueError):
            return None
        if not math.isfinite(target_sv) or not 50.0 <= target_sv <= 350.0:
            return None

        # Rolling median removes isolated probe spikes before reach/overshoot
        # metrics. Invalid sentinels never enter either the filter or RoR.
        filtered_ctrl: list[float] = []
        filter_window: deque[float] = deque(maxlen=5)
        for value in ctrl_slice:
            if isinstance(value, (int, float)) and value != -1 and math.isfinite(value):
                filter_window.append(float(value))
                filtered_ctrl.append(float(median(filter_window)))
            else:
                filtered_ctrl.append(-1.0)

        # Dépassement / sous-dépassement mesurés contre la vraie SV enregistrée.
        max_bt = max((v for v in filtered_ctrl if v != -1), default=target_sv)
        overshoot = max(0.0, max_bt - target_sv)
        undershoot = max(0.0, target_sv - max_bt)

        # Temps pour atteindre la cible ET l'index absolu correspondant. sv_reach_idx
        # borne le début de la phase de maintien (voir hold power) : premier point à
        # moins de 2°C sous la SV enregistrée.
        reach_thresh = target_sv - 2.0
        time_to_sv = 0.0
        sv_reach_idx: int | None = None
        for k, bt_val in enumerate(filtered_ctrl):
            if bt_val != -1 and bt_val >= reach_thresh:
                time_to_sv = t_slice[k] - t_slice[0]
                sv_reach_idx = i0 + k          # index absolu dans timex
                break


        # Robust ramp RoR: only the rising approach up to first target reach,
        # with impossible adjacent slopes removed. The 95th percentile is a
        # reproducible peak, unlike the maximum of a noisy one-second series.
        ramp_stop = (sv_reach_idx - i0) if sv_reach_idx is not None else len(t_slice) - 1
        rors: list[float] = []
        for k in range(1, min(len(t_slice), ramp_stop + 1)):
            if filtered_ctrl[k - 1] == -1 or filtered_ctrl[k] == -1:
                continue
            dt = t_slice[k] - t_slice[k - 1]
            if dt <= 0:
                continue
            ror = (filtered_ctrl[k] - filtered_ctrl[k - 1]) / (dt / 60.0)
            if 0.0 < ror <= 120.0:
                rors.append(ror)

        mean_ror = _robust_centre(rors)
        peak_ror = _robust_peak(rors)

        # Détection de stabilisation : variance sur les 30 dernières secondes
        hold_slice = [b for t_, b in zip(t_slice, filtered_ctrl)
                      if t_ >= t_slice[-1] - 30 and b != -1]
        was_stable = False
        stabilise_extra = 0.0
        if len(hold_slice) >= 5:
            var = stdev(hold_slice) if len(hold_slice) > 1 else 99.0
            # A flat plateau BELOW SV is a failed approach, not a hold — require
            # both flatness (var < 0.8) AND tight proximity to the recorded SV (±0.8°C),
            # so a hot-parked drum cannot certify itself as "stable".
            plateau_mean = mean(hold_slice)
            was_stable = var < 0.8 and abs(plateau_mean - target_sv) <= 0.8
            for k in range(5, len(t_slice)):
                window_bt = [v for v in filtered_ctrl[max(0, k - 5): k] if v != -1]
                if (len(window_bt) > 1 and stdev(window_bt) < 0.8
                        and abs(mean(window_bt) - target_sv) <= 0.8):
                    stabilise_extra = t_slice[k] - time_to_sv - t_slice[0]
                    break

        # Puissance hold = le canal brûleur continu (extra-device 'Burner'), pas les
        # événements spéciaux (trop épars, dernier event avant CHARGE souvent une valeur de rampe périmée).
        burner = self._burner_channel(data)
        had_burner_channel = burner is not None
        hold_power_vals: list[float] = []
        if was_stable and sv_reach_idx is not None and burner is not None:
            bvals, btimex = burner
            t_hi = timex[i1]
            t_lo = max(timex[sv_reach_idx], t_hi - 30.0)
            hold_power_vals = [
                float(bvals[j])
                for j in range(min(len(bvals), len(btimex)))
                if t_lo <= btimex[j] <= t_hi
                and isinstance(bvals[j], (int, float))
                and 0.0 < bvals[j] <= 100.0          # rejette -1 et valeurs aberrantes
            ]
        if sv_reach_idx is not None:
            hold_span = min(30.0, timex[i1] - timex[sv_reach_idx])
        else:
            hold_span = 0.0
        hold_mean_pwr = (
            float(median(hold_power_vals))
            if hold_span >= 20.0 and len(hold_power_vals) >= 10 else 0.0)

        # Prefer the roast's own epoch for the burner-calibration gate: file mtime is
        # bumped by any copy/backup/sync and would let a pre-calibration roast sneak past the cutoff.
        _epoch = data.get("roastepoch")
        roast_ts = float(_epoch) if isinstance(_epoch, (int, float)) and _epoch > 0 else path.stat().st_mtime

        return RoastPreheatMetrics(
            timestamp=roast_ts,
            target_sv=target_sv,
            ambient=ambient,
            mean_ramp_ror=mean_ror,
            peak_ramp_ror=peak_ror,
            overshoot_c=overshoot,
            undershoot_c=undershoot,
            time_to_sv_sec=time_to_sv,
            stabilise_time_sec=stabilise_extra,
            hold_mean_power=hold_mean_pwr,
            was_stable=was_stable,
            target_is_recorded_sv=True,   # guaranteed: unmarked roasts returned None above
            had_burner_channel=had_burner_channel,
            zone_fuzzy_start_used=params.zone_fuzzy_start_used,
            coast_lookahead_sec_used=params.coast_lookahead_sec_used,
            max_burner_used=params.max_burner_used,
            base_hold_power_used=params.base_hold_power_used,
        )

    @staticmethod
    def _nearest_idx(timex: List[float], t: float) -> int:
        """Index de la valeur la plus proche de t dans timex."""
        return min(range(len(timex)), key=lambda i: abs(timex[i] - t))

    @staticmethod
    def _burner_channel(data: dict) -> "tuple[list, list] | None":
        """Locate the continuous burner-power extra-device channel and its own timebase.

        Burner power is logged as an Artisan extra device (name ~ 'Burner'; note the
        real-world typo 'Buner' — we match the 'bun' substring), 0–100 %, sampled ~1 Hz
        with its OWN timebase `extratimex[i]` (independent of the main `timex`). This is
        the only trustworthy hold-power source: the type-3 special-event stream is too
        sparse (a flat hold emits none) and its last pre-CHARGE value is a stale ramp
        reading. Returns (values, timebase) for the first matching channel, else None.
        Shared by _extract_metrics and the offline preheat_corpus_report tool.
        """
        etx = data.get("extratimex", [])
        # Current Skywalker/SkyCommand actuator devices use Artisan's
        # generic event label (`{3}`), not the word Burner. Resolve their stable
        # save-time identity first; channel 1 / extratemp1 is the burner echo.
        name_map = data.get("tilau_name_map") or {}
        for raw_slot, key in name_map.items():
            try:
                slot = int(raw_slot)
            except (TypeError, ValueError):
                continue
            if key in {"skywalker_pf", "skycommand_pf"}:
                values = data.get("extratemp1", [])
                if (slot < len(values) and slot < len(etx)
                        and isinstance(values[slot], list)
                        and isinstance(etx[slot], list)
                        and values[slot] and etx[slot]):
                    return values[slot], etx[slot]
        for arr_key, name_key in (("extratemp1", "extraname1"), ("extratemp2", "extraname2")):
            names = data.get(name_key, [])
            temps = data.get(arr_key, [])
            for i, nm in enumerate(str(x).lower() for x in names):
                if ("bun" in nm or "burn" in nm) and i < len(temps) and i < len(etx):
                    vals, tb = temps[i], etx[i]
                    if isinstance(vals, list) and isinstance(tb, list) and vals and tb:
                        return vals, tb
        return None

    def load_window(self) -> List[RoastPreheatMetrics]:
        """Charge et retourne les métriques des `window` dernières torréfactions."""
        started_at = time.perf_counter()
        results = []
        candidates = self._list_recent()
        for p in candidates:
            # Fail-safe: a single malformed .alog must never abort the whole history
            # load (which would fail the preheat PID start) — skip it and keep learning.
            try:
                m = self._extract_metrics(p)
            except Exception as exc:  # noqa: BLE001
                _logd.debug(f"AlogScanner: {p.name} ignoré (extraction impossible: {exc})")
                continue
            if m is not None:
                results.append(m)
                if len(results) >= self.window:
                    break
        _logd.debug(
            f"AlogScanner: {len(results)} admissible(s) parmi les "
            f"{len(candidates)} profil(s) retenus sur index dans {self.alog_dir} "
            f"(fenêtre mémoire {self.window}, plafond de lecture {self.scan_budget}) "
            f"en {(time.perf_counter() - started_at) * 1000.0:.0f} ms")
        return results


# ─────────────────────────────────────────────────────────────────────────────
# 2. AdaptiveMemory
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ThermalModel:
    """Learned thermal characteristics for this roaster at given conditions."""
    thermal_mass: float = 0.608         # °C per % burner power per minute
    response_lag: float = 2.3           # seconds, burner change → temp response
    preheat_duration_optimal: float = 360.0  # target preheat time in seconds (6 min default)
    hold_power: float = 40.0            # learned hold power %
    confidence: float = 0.0             # 0.0 (no data) → 1.0 (full window)
    n_samples: int = 0                  # number of roasts aggregated


@dataclass
class LearnedParams:
    """Paramètres PID appris sur la fenêtre glissante."""
    # Correction sur la zone fuzzy : si overshoot moyen > 1°C → reculer la zone
    zone_fuzzy_start_adj: float = 0.0       # delta à appliquer à zone_fuzzy_start
    # Correction sur le coast_lookahead : si overshoot → anticiper davantage
    coast_lookahead_adj: float = 0.0        # delta en secondes
    # Correction sur max_burner : si la montée est trop lente → monter légèrement
    max_burner_adj: float = 0.0             # delta en %
    # Correction sur hold_power : apprendre la puissance réelle de maintien
    hold_power_override: Optional[float] = None  # None = utiliser formule
    # Confiance : 0.0 (pas de données) → 1.0 (fenêtre complète)
    confidence: float = 0.0
    n_samples: int = 0


class AdaptiveMemory:
    """
    Agrège les métriques historiques pour produire des corrections de paramètres.

    Principe d'apprentissage :
    ─────────────────────────
    • Overshoot moyen  > 2°C  → reculer zone_fuzzy_start (-0.005 par °C)
                                 ET augmenter coast_lookahead (+0.5s par °C)
    • Overshoot moyen  < 0.3°C → avancer zone_fuzzy_start (+0.003)
                                  (évite de freiner trop tôt = montée lente)
    • RoR moyen < 8°C/min      → légère hausse max_burner (+2%)
    • RoR moyen > 20°C/min     → légère baisse max_burner (-2%)
    • hold_mean_power observé  → override si confiance suffisante
    """

    MAX_ADJ_ZONE = 0.06     # delta max autorisé sur zone_fuzzy_start
    MAX_ADJ_COAST = 4.0     # delta max autorisé sur coast_lookahead (s)
    MAX_ADJ_BURNER = 8.0    # delta max autorisé sur max_burner (%)

    def __init__(self, window: int = 10):
        self.window = window
        self._history: deque = deque(maxlen=window)

    def push(self, m: RoastPreheatMetrics) -> None:
        self._history.append(m)

    def push_all(self, metrics: List[RoastPreheatMetrics]) -> None:
        for m in metrics:
            self._history.append(m)

    def compute(self, current_sv: float) -> LearnedParams:
        """
        Calcule les corrections basées sur les torréfactions passées dont la
        consigne était proche de current_sv (± 15°C).
        """
        relevant = [
            m for m in self._history
            if abs(m.target_sv - current_sv) <= 15.0
        ]
        n = len(relevant)
        if n == 0:
            return LearnedParams(confidence=0.0, n_samples=0)

        confidence = min(1.0, n / self.window)

        # ── Overshoot ──────────────────────────────────────────────────
        mean_overshoot = mean(m.overshoot_c for m in relevant)
        # Pénalité progressive : +1°C overshoot → zone recule de 0.005
        zone_adj = 0.0
        if mean_overshoot > 2.0:
            zone_adj = -min(self.MAX_ADJ_ZONE, (mean_overshoot - 2.0) * 0.005)
        elif mean_overshoot < 0.3 and all(m.was_stable for m in relevant):
            zone_adj = min(0.015, (0.3 - mean_overshoot) * 0.003)

        # coast_lookahead : 0.5s par °C de dépassement au-delà de 1°C
        coast_adj = 0.0
        if mean_overshoot > 1.0:
            coast_adj = min(self.MAX_ADJ_COAST, (mean_overshoot - 1.0) * 0.5)
        elif mean_overshoot < 0.2:
            coast_adj = max(-2.0, -0.3)

        # ── RoR de montée ──────────────────────────────────────────────
        mean_ror = mean(m.mean_ramp_ror for m in relevant)
        burner_adj = 0.0
        if mean_ror < 8.0:
            burner_adj = min(self.MAX_ADJ_BURNER, (8.0 - mean_ror) * 0.4)
        elif mean_ror > 20.0:
            burner_adj = max(-self.MAX_ADJ_BURNER, -(mean_ror - 20.0) * 0.3)

        # ── Hold power ─────────────────────────────────────────────────
        hold_vals = [m.hold_mean_power for m in relevant if m.hold_mean_power > 0]
        hold_override = None
        if len(hold_vals) >= 3 and confidence >= 0.5:
            hold_override = mean(hold_vals)

        # Pondération par confiance : corrections atténuées si peu de données
        lp = LearnedParams(
            zone_fuzzy_start_adj=zone_adj * confidence,
            coast_lookahead_adj=coast_adj * confidence,
            max_burner_adj=burner_adj * confidence,
            hold_power_override=hold_override,
            confidence=confidence,
            n_samples=n,
        )
        _logd.debug(
            f"AdaptiveMemory [{n} samples, conf={confidence:.2f}] "
            f"zone_adj={zone_adj:+.4f} coast_adj={coast_adj:+.1f}s "
            f"burner_adj={burner_adj:+.1f}% hold={hold_override}"
        )
        return lp

    def get_thermal_characteristics(
        self,
        target_sv: float,
        ambient: AmbientConditions,
        kernel_type: str = "triangular",
        kernel_sigma: float = 1.0
    ) -> ThermalModel:
        """
        Query historical roasts to find thermal model for this target + ambient.

        Uses weighted aggregation with specified kernel:
        - "triangular": FIR roasters (Skywalker, Kaleido) — fast response
        - "gaussian": convection/induction (Bullet, Roest) — thermal inertia

        Weights decay with distance but never reach zero for gaussian.
        Stability boost: 1.5× if roast.was_stable (smooth convergence to SV).

        Returns aggregated thermal characteristics with confidence based on Σ(weights).
        """
        # Select kernel function
        if kernel_type == "gaussian":
            weight_fn = lambda roast_m: weight_gaussian(
                roast_m.target_sv, roast_m.ambient,
                target_sv, ambient,
                sigma=kernel_sigma
            )
        else:  # default: triangular
            weight_fn = lambda roast_m: weight_triangular(
                roast_m.target_sv, roast_m.ambient,
                target_sv, ambient
            )

        # Compute weighted aggregates across ALL historical roasts
        weighted_mass = 0.0
        weighted_lag = 2.3  # default response lag
        weighted_hold = 0.0
        sum_weights = 0.0
        stable_count = 0

        for roast in self._history:
            base_weight = weight_fn(roast)

            # Stability boost: 1.5× for roasts that converged smoothly
            stability_factor = 1.5 if roast.was_stable else 1.0
            weight = base_weight * stability_factor

            if weight > 1e-6:  # Only aggregate if weight is non-negligible
                # Thermal mass from ramp RoR (approximate from 0.6°C/(%.min) baseline)
                estimated_ramp_power = max(15.0, roast.mean_ramp_ror / 0.6)
                thermal_mass_obs = roast.mean_ramp_ror / max(1.0, estimated_ramp_power)

                weighted_mass += weight * thermal_mass_obs
                weighted_hold += weight * roast.hold_mean_power
                sum_weights += weight
                if roast.was_stable:
                    stable_count += 1

        # Finalize aggregates
        if sum_weights > 0:
            thermal_mass = weighted_mass / sum_weights
            response_lag = weighted_lag  # TODO: extract from roast metrics if available
            hold_power = weighted_hold / sum_weights
            # Confidence: normalized sum of weights (higher = more/better matched roasts)
            confidence = min(1.0, sum_weights / len(self._history)) if self._history else 0.0
            n_samples = stable_count
        else:
            # No roasts matched even loosely (empty history)
            return ThermalModel(confidence=0.0, n_samples=0)

        model = ThermalModel(
            thermal_mass=thermal_mass,
            response_lag=response_lag,
            preheat_duration_optimal=360.0,  # default 6 min
            hold_power=hold_power,
            confidence=confidence,
            n_samples=n_samples,
        )

        _logd.debug(
            f"ThermalModel [SV={target_sv:.0f}°C, ambient={ambient.temp_ambient:.1f}°C, "
            f"kernel={kernel_type}] | Σ(weights)={sum_weights:.1f}, "
            f"stable={stable_count}: thermal_mass={thermal_mass:.3f}°C/(%.min), "
            f"response_lag={response_lag:.1f}s, hold={hold_power:.1f}%, "
            f"confidence={confidence:.2f}"
        )

        return model


# ─────────────────────────────────────────────────────────────────────────────
# 3. AmbientCorrector
# ─────────────────────────────────────────────────────────────────────────────

class AmbientCorrector:
    """
    Calcule un facteur correctif de puissance basé sur les conditions ambiantes.

    Modèle physique simplifié :
    ───────────────────────────
    La perte thermique d'un tambour est approximée par :
        Q_loss ∝ (T_drum - T_ambient)

    À température ambiante de référence (20°C), le hold power est calibré.
    Si T_ambient descend, les pertes augmentent → correction positive.
    L'humidité influence la capacité thermique de l'air (faible effet).
    La pression influence la densité de l'air (convection naturelle).

    Retourne un facteur multiplicatif centré sur 1.0.
    """

    REF_TEMP = 20.0         # °C de référence
    REF_HUMIDITY = 50.0     # %RH de référence
    REF_PRESSURE = 1013.25  # hPa de référence

    # Sensibilités empiriques (à affiner via les alogs)
    K_TEMP = 0.003          # 0.3% de correction par °C d'écart ambiant
    K_HUMIDITY = 0.0005     # 0.05% par %RH d'écart (effet mineur)
    K_PRESSURE = 0.0002     # 0.02% par hPa d'écart (très faible)

    def compute_factor(self, ambient: AmbientConditions) -> float:
        """
        Retourne un facteur multiplicatif à appliquer sur la puissance de hold.
        Ex : 0.97 = réduire de 3%, 1.04 = augmenter de 4%.
        """
        if not ambient.is_valid():
            return 1.0

        delta_temp = self.REF_TEMP - ambient.temp_ambient         # + si froid
        delta_humidity = ambient.humidity - self.REF_HUMIDITY     # + si humide
        delta_pressure = self.REF_PRESSURE - ambient.pressure     # + si basse pression

        factor = (
            1.0
            + self.K_TEMP * delta_temp
            + self.K_HUMIDITY * delta_humidity
            + self.K_PRESSURE * delta_pressure
        )
        # Borne ±15% pour éviter les corrections absurdes
        factor = max(0.85, min(1.15, factor))
        _logd.debug(
            f"AmbientCorrector: T={ambient.temp_ambient:.1f}°C "
            f"HR={ambient.humidity:.0f}% P={ambient.pressure:.0f}hPa "
            f"→ factor={factor:.4f}"
        )
        return factor


# ─────────────────────────────────────────────────────────────────────────────
# 4. StabilisationDetector
# ─────────────────────────────────────────────────────────────────────────────

class StabilisationDetector:
    """
    Détecte en temps réel si la température est stabilisée autour de la consigne.

    Méthode :
      • Fenêtre glissante de `window_sec` secondes de températures
      • Stable si : mean ∈ [SV - tol, SV + tol] ET stdev < stability_std
      • Dérive positive/négative détectée via régression linéaire sur la fenêtre

    Expose :
      is_stable()       → bool
      slope_c_per_min() → pente de dérive (°C/min), 0 si stable
      seconds_stable    → durée de stabilisation continue
    """

    def __init__(self, window_sec: float = 30.0, tolerance_c: float = 1.0,
                 stability_std: float = 0.5, polling_dt: float = 1.0):
        self.window_sec = float(window_sec)
        self.tolerance_c = tolerance_c
        self.stability_std = stability_std
        self.polling_dt = polling_dt
        self._temps: deque[float] = deque()
        self._times: deque[float] = deque()
        self.seconds_stable: float = 0.0
        self._stable_since: Optional[float] = None

    def update(self, t_c: float, sv_c: float, *, now: float | None = None) -> None:
        """Ajouter une mesure (°C interne)."""
        now = time.perf_counter() if now is None else float(now)
        self._temps.append(t_c)
        self._times.append(now)
        cutoff = now - self.window_sec
        while len(self._times) > 1 and self._times[1] <= cutoff:
            self._times.popleft()
            self._temps.popleft()

        if self._check_stable(sv_c):
            if self._stable_since is None:
                self._stable_since = now
            self.seconds_stable = now - self._stable_since
        else:
            self._stable_since = None
            self.seconds_stable = 0.0

    def reset(self) -> None:
        """Forget every sample and stability duration before a new preheat."""
        self._temps.clear()
        self._times.clear()
        self.seconds_stable = 0.0
        self._stable_since = None

    def _check_stable(self, sv_c: float) -> bool:
        n = len(self._temps)
        if n < 5 or not self.has_full_window():
            return False
        m = mean(self._temps)
        s = stdev(self._temps) if n > 1 else 99.0
        return abs(m - sv_c) <= self.tolerance_c and s <= self.stability_std

    def mean_temp(self) -> Optional[float]:
        """Mean temperature over the current window (°C), or None if too few
        samples to be meaningful. Used at preheat-complete to read the settle point."""
        if len(self._temps) < 3:
            return None
        return mean(self._temps)

    def has_full_window(self) -> bool:
        """True once samples span the configured wall-clock observation window."""
        return (
            len(self._times) >= 2
            and self._times[-1] - self._times[0] >= self.window_sec
        )

    def is_stable(self, min_duration_sec: float = 10.0) -> bool:
        """Retourne True si stable depuis au moins min_duration_sec secondes."""
        return self.seconds_stable >= min_duration_sec

    def slope_c_per_min(self) -> float:
        """
        Pente de la température sur la fenêtre (°C/min).
        Positive = montée, négative = descente.
        """
        temps = list(self._temps)
        times = list(self._times)
        n = len(temps)
        if n < 3:
            return 0.0
        # Régression linéaire simple (moindres carrés)
        t0 = times[0]
        xs = [(t - t0) for t in times]    # secondes relatives
        x_mean = mean(xs)
        y_mean = mean(temps)
        num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, temps))
        den = sum((x - x_mean) ** 2 for x in xs)
        if den == 0:
            return 0.0
        slope_per_sec = num / den          # °C/s
        return slope_per_sec * 60.0        # °C/min

    def ramp_quality(self) -> str:
        """Évaluation qualitative de la pente de montée."""
        slope = self.slope_c_per_min()
        if slope > 15:
            return "RAMP_FAST"
        elif slope > 5:
            return "RAMP_NORMAL"
        elif slope > 0.5:
            return "RAMP_SLOW"
        elif abs(slope) <= 0.5:
            return "PLATEAU"
        else:
            return "COOLING"


# ─────────────────────────────────────────────────────────────────────────────
# 5. AdaptivePIDMixin
# ─────────────────────────────────────────────────────────────────────────────

class AdaptivePIDMixin:
    """
    Mixin à intégrer dans TilauPreheatPID.

    Hypothèses sur self (hérité de TilauPreheatPID) :
      self.cfg                  → PIDConfig
      self._precompute_targets() → méthode existante
      self._to_c(val)           → conversion native→°C
      self.aw.qmc               → accès Artisan QMC

    Usage dans TilauPreheatPID.__init__ :
        # Après super().__init__() / init normal :
        self._adaptive_init(alog_dir="/chemin/vers/alogs")

    Usage dans cycle() :
        self._on_cycle(t_c_interne, burner_pct)

    Usage dans stop() ou quand stable détecté :
        self._on_preheat_complete()

 ── Simulator isolation (INVARIANT) ──────────────────────────────
    A simulated preheat (``aw.simulator is not None``) MUST NOT persist or learn
    anything: it may run the control law and read learned params, but it never
    trains the real controller. This is enforced at every write path — keep all
    three guards if this code is refactored:
      • _on_preheat_complete()  → returns before _learn_law_params() (no learning)
      • _save_law_params()      → no per-SV P_ss/lead write
      • _migrate_persisted_law()→ no law_version stamp / no persisted-state migration
    load_law_params() only reads, so a simulated run gets the learned (or default)
    params and writes nothing back. Running a preheat in Simulator is therefore a
    safe dry-run: it cannot alter your real learned P_ss/lead nodes.
    """
    cfg: _PIDConfigLike
    p_ss: float
    lead_sec: float
    _base_hold_power: float
    # ── Cross-roast control-law learning (P_ss + lead_sec) ───────────
    # Replaces the retired fuzzy-zone integrator. Only two knobs are learned, both
    # consumed directly by compute_fuzzy_power via load_law_params():
    #   P_ss     — steady hold power near SV (closes the proportional droop over roasts)
    #   lead_sec — projection lead (raise → brake earlier when a roast overshot)
    _PSS_EMA_ALPHA: float = 0.3        # blend weight for a clean (±0.5°C) plateau's measured hold
    _PSS_DROOP_GAIN: float = 0.5       # %/°C nudge when it settles stably but off-SV
    _PSS_MIN: float = 5.0              # floor on learned steady hold
    _LEAD_OVERSHOOT_GAIN: float = 0.4  # +s of lead per °C of overshoot beyond the deadband
    _LEAD_UNDERSHOOT_STEP: float = 1.0 # −s of lead when SV was never reached
    _OVERSHOOT_DEADBAND_C: float = 1.5 # overshoot tolerated before we lengthen the lead
    _HOLD_BAND_C: float = 0.8          # |t−SV| within which a burner sample counts as "hold"
    _SETTLE_BAND_C: float = 0.5        # plateau within this of SV ⇒ trust the measured hold power
    _SETTLE_PROXIMITY_C: float = 5.0   # a quasi-flat tail this close to SV is a settle point to correct
                                       # (below it we assume a mid-ramp plateau, not a real hold)
    _APPROACH_MIN_C: float = 10.0      # a roast must have climbed within this of SV to count as a real
                                       # approach — guards lead learning against early aborts
    _MIN_LEARNING_SESSION_SEC: float = 60.0  # reject starts/stops too short to identify the response
    _MIN_POST_REACH_SEC: float = 15.0   # observe the coast before attributing overshoot to lead
    _MIN_HOLD_DWELL_SEC: float = 20.0   # continuous in-band hold required for measured P_ss
    _MIN_HOLD_SAMPLES: int = 15
    _MAX_PSS_STEP: float = 2.0          # maximum persisted movement from one qualified session
    _MAX_LEAD_STEP: float = 0.8
    _LAW_EDGE_MAX_DISTANCE_C: float = 15.0  # bounded nearest-node use outside learned range
    _LAW_MAX_INTERPOLATION_GAP_C: float = 40.0  # do not bridge unrelated thermal regimes
    _LAW_VERSION: int = 4              # v4 stores exact-SV nodes and interpolates continuously
    # ── Cold-start seeding from the historical alog corpus ────────────
    # When no exact/interpolated SV node is available, seed P_ss and lead_sec from past
    # roasts instead of a flat default. P_ss uses hold_mean_power but ONLY from
    # post-calibration alogs (pre-Nov-2025 burner values are ~2× the real reading);
    # lead uses the observed overshoot, which is a temperature and thus calibration-
    # independent, so it may use the whole corpus.
    _SEED_SV_WINDOW_C: float = 15.0    # roasts within ±this of the target SV are relevant
    _SEED_MIN_ROASTS: int = 3          # need at least this many to trust a seed (else fall back)
    _SEED_LEAD_OVERSHOOT_GAIN: float = 0.4  # +s of lead per °C of mean historical overshoot beyond deadband
    # Burner-calibration cutoff: alogs older than 2025-11-01 have doubled fire values
    # (see corpus notes) and must NOT seed the absolute hold power P_ss.
    _SEED_CALIB_CUTOFF_EPOCH: float = 1761955200.0  # 2025-11-01 00:00 UTC
    # Offline thermal candidates never become a control prior directly.
    # They first need three consecutive qualified real-preheat shadow passes.
    _THERMAL_STATE_VERSION: int = 1
    _THERMAL_REQUIRED_PASSES: int = 3

    def _adaptive_init(
        self,
        alog_dir: Optional[str] = None,
        window: int = 10,
        ambient: Optional[AmbientConditions] = None,
        aw: ApplicationWindow | None = None ,
        scan_budget: int | None = None,
    ) -> None:
        """Initialise tous les sous-systèmes adaptatifs."""
        # Répertoire alog : fixé par l'application (clé QSettings 'alogDirectory',
        # même source que routine_check / roast_plan_model / beancave). On ne DEVINE
        # jamais — deviner risque de scanner le mauvais dossier.
        if alog_dir is None:
            alog_dir = self._configured_alog_dir()

        self.aw=aw

        self._alog_scanner = AlogScanner(alog_dir, window, aw=self.aw,
                                         scan_budget=scan_budget)
        self._adaptive_memory = AdaptiveMemory(window)
        self._ambient_corrector = AmbientCorrector()
        self._stabilisation_detector = StabilisationDetector(
            window_sec=30.0,
            tolerance_c=1.0,
            stability_std=0.5,
            polling_dt=getattr(self.cfg, "polling_dt", 1.0),
        )
        self._current_ambient = ambient or AmbientConditions()
        self._learned: Optional[LearnedParams] = None
        self._ambient_factor: float = 1.0

        # Métriques en cours d'accumulation pour la torréfaction actuelle
        self._session_rors: List[float] = []
        self._session_burner_hold: List[float] = []
        self._session_hold_samples: List[float] = []   # burner samples within ±_HOLD_BAND_C of SV → P_ss learning
        self._session_start_time: float = 0.0
        self._session_reached_sv: bool = False
        self._session_reach_time: float = 0.0
        self._session_max_bt: float = 0.0
        self._session_filtered_max_bt: float = 0.0
        self._session_temp_filter: deque[float] = deque(maxlen=5)
        self._session_hold_started_at: Optional[float] = None
        self._session_hold_last_at: Optional[float] = None
        # Candidate/shadow state is a sidecar + QSettings only. Artisan's
        # ProfileData remains untouched, and the observer has no actuator callback.
        self._thermal_candidate: ThermalModelCandidate | None = None
        self._thermal_shadow: ThermalShadowSession | None = None
        self._thermal_active: bool = False

        # Chargement initial de l'historique — hors du thread GUI.
        # Le gestionnaire est construit au clic ON, et la fenêtre de lecture
        # vaut jusqu'à `scan_budget` profils : la parser sur place gelait
        # l'interface ~1,5 s avant que le monitoring ne démarre. Le préchauffage
        # se joint au worker au START, bien après le clic.
        self._history_ready = threading.Event()
        self._history_thread: threading.Thread | None = None
        self._start_history_worker()
        # One-time migration: drop the pre-redesign relay-law persisted state.
        self._migrate_persisted_law()
        _logd.debug(
            f"AdaptivePIDMixin initialisé | alog_dir={alog_dir} "
            f"window={window} | historique en cours de chargement"
        )

    # ── Chargement de l'historique en tâche de fond ───────────────────────────

    def _start_history_worker(self) -> None:
        """Charge le corpus dans un thread dédié. Ne touche que des fichiers.

        Le worker n'accède ni à Qt ni à qmc : le scanner a figé la machine et la
        voie de contrôle à sa construction, sur le thread GUI.
        """
        self._history_ready.clear()

        def _work() -> None:
            try:
                self._load_history()
            except Exception as exc:  # noqa: BLE001
                _logd.debug(f"Chargement de l'historique adaptatif abandonné : {exc}")
            finally:
                self._history_ready.set()

        self._history_thread = threading.Thread(
            target=_work, name="TilauPIDHistory", daemon=True)
        self._history_thread.start()

    def _ensure_history_loaded(self, timeout: float = 30.0) -> None:
        """Attend la fin du worker. Sans effet une fois l'historique chargé.

        Un dépassement laisse la mémoire adaptative partielle plutôt que de
        retenir le START : un préchauffage sans apprentissage reste conduit par
        les valeurs par défaut.
        """
        if self._history_ready.is_set():
            return
        started_at = time.perf_counter()
        if not self._history_ready.wait(timeout):
            _logd.warning("Historique adaptatif toujours en chargement — "
                          "démarrage sans apprentissage complet")
            return
        _logd.debug("TilauPID: historique adaptatif attendu "
                    f"{(time.perf_counter() - started_at) * 1000.0:.0f} ms au START")

    @staticmethod
    def _configured_alog_dir() -> str:
        """Répertoire alog canonique tel que fixé par l'application.

        Lit la clé QSettings 'alogDirectory' — la même source utilisée par
        routine_check, roast_plan_model, beancave et l'onboarding. On ne devine
        pas le dossier ; s'il n'est pas configuré, on retourne "" (le scanner
        traite un répertoire inexistant comme un corpus vide, sans planter).
        """
        alog_dir = QSettings().value("alogDirectory", "", str) or ""
        if not alog_dir:
            _logd.warning("QSettings 'alogDirectory' non configuré — corpus vide.")
        return alog_dir

    def _load_history(self) -> None:
        """Charge les métriques historiques et calcule les corrections initiales."""
        self._adaptive_memory._history.clear()   # ← évite les doublons
        metrics = self._alog_scanner.load_window()
        self._adaptive_memory.push_all(metrics)
        self._refresh_learned()

    # ── Offline model → shadow → bounded prior promotion ────────────

    def _thermal_state_prefix(self, candidate: ThermalModelCandidate) -> str:
        machine, channel = self._law_context()
        return (
            f"tilaupid/thermal/v{self._THERMAL_STATE_VERSION}/"
            f"{machine}/{channel}/{candidate.fingerprint}"
        )

    @staticmethod
    def _thermal_promotion_state(settings: QSettings, prefix: str) -> ThermalPromotionState:
        return ThermalPromotionState(
            consecutive_passes=int(settings.value(
                f"{prefix}/consecutive_passes", 0, int) or 0),
            qualified_sessions=int(settings.value(
                f"{prefix}/qualified_sessions", 0, int) or 0),
            failed_sessions=int(settings.value(
                f"{prefix}/failed_sessions", 0, int) or 0),
            active=bool(settings.value(f"{prefix}/active", False, bool)),
        )

    def _load_thermal_candidate(self) -> None:
        """Read one tiny sidecar and arm a no-output shadow observer.

        This is O(file size), independent of the roast archive size. A missing,
        malformed or context-mismatched sidecar is ignored fail-closed.
        """
        self._thermal_candidate = None
        self._thermal_shadow = None
        self._thermal_active = False
        path = Path(self._alog_scanner.alog_dir) / THERMAL_MODEL_FILENAME
        if not path.is_file():
            return
        try:
            candidate = load_candidate(path)
        except (OSError, ValueError) as exc:
            _logd.warning(f"TilauPID thermal candidate ignored: {exc}")
            return
        machine, channel = self._law_context()
        if (candidate.machine_fingerprint != machine
                or candidate.control_channel != channel):
            _logd.info(
                "TilauPID thermal candidate ignored: "
                f"context {candidate.machine_fingerprint}/{candidate.control_channel} "
                f"!= {machine}/{channel}")
            return
        state = self._thermal_promotion_state(
            QSettings(), self._thermal_state_prefix(candidate))
        self._thermal_candidate = candidate
        self._thermal_active = state.active
        if getattr(getattr(self, "aw", None), "simulator", None) is None:
            self._thermal_shadow = ThermalShadowSession(candidate)
        _logd.info(
            f"Thermal model {candidate.fingerprint}: "
            f"{'ACTIVE prior' if state.active else 'SHADOW only'}; "
            f"shadow passes={state.consecutive_passes}/{self._THERMAL_REQUIRED_PASSES}")

    def _thermal_prior_params(self) -> tuple[Optional[float], Optional[float]]:
        """Return the promoted model's bounded cold-start prior, never a command."""
        candidate = getattr(self, "_thermal_candidate", None)
        if candidate is None or not getattr(self, "_thermal_active", False):
            return None, None
        ambient = getattr(self, "_current_ambient", AmbientConditions()).temp_ambient
        applied_hold = candidate.equilibrium_power_pct(self.cfg.target_sv, ambient)
        # compute_fuzzy_power applies AmbientCorrector once more; neutralise that
        # multiplier so the physical model's ambient loss is not counted twice.
        factor = self._ambient_factor if self._ambient_factor > 1e-6 else 1.0
        return applied_hold / factor, candidate.response_lag_sec

    def _finish_thermal_shadow(self) -> ThermalShadowResult | None:
        """Score a completed real session and persist promotion evidence."""
        shadow = self._thermal_shadow
        candidate = self._thermal_candidate
        if shadow is None or candidate is None:
            return None
        result = shadow.finish()
        settings = QSettings()
        prefix = self._thermal_state_prefix(candidate)
        old_state = self._thermal_promotion_state(settings, prefix)
        new_state = old_state.advance(result, self._THERMAL_REQUIRED_PASSES)
        settings.setValue(f"{prefix}/last_reason", result.reason)
        settings.setValue(f"{prefix}/last_rmse_c", result.rmse_c)
        settings.setValue(f"{prefix}/last_bias_c", result.bias_c)
        settings.setValue(f"{prefix}/last_p95_c", result.p95_abs_error_c)
        settings.setValue(f"{prefix}/last_samples", result.n_samples)
        if result.qualified:
            settings.setValue(f"{prefix}/consecutive_passes", new_state.consecutive_passes)
            settings.setValue(f"{prefix}/qualified_sessions", new_state.qualified_sessions)
            settings.setValue(f"{prefix}/failed_sessions", new_state.failed_sessions)
            settings.setValue(f"{prefix}/active", new_state.active)
        settings.sync()
        self._thermal_active = new_state.active
        _logd.info(
            f"Thermal shadow {candidate.fingerprint}: {result.reason}; "
            f"RMSE={result.rmse_c:.2f}°C bias={result.bias_c:+.2f}°C "
            f"P95={result.p95_abs_error_c:.2f}°C samples={result.n_samples}; "
            f"passes={new_state.consecutive_passes}/{self._THERMAL_REQUIRED_PASSES} "
            f"active={new_state.active}")
        return result

    def _refresh_learning_context(self) -> bool:
        """Freeze the currently selected machine/input for one preheat session.

        The PID manager can outlive changes made in Roast Setup. Rebuilding the
        lightweight scanner at START ensures both corpus selection and QSettings
        keys follow the selection that will actually control this session.
        Returns whether the corpus context changed and therefore needs reloading.
        """
        scanner = self._alog_scanner
        refreshed = AlogScanner(
            str(scanner.alog_dir),
            window=scanner.window,
            aw=self.aw,
            scan_budget=scanner.scan_budget,
        )
        changed = (
            refreshed.machine_fingerprint != scanner.machine_fingerprint
            or refreshed.control_channel != scanner.control_channel
        )
        self._alog_scanner = refreshed
        return changed

    def _refresh_learned(self) -> None:
        """Recalcule les paramètres appris et met à jour cfg."""
        sv = getattr(self.cfg, "target_sv", 200.0)
        self._learned = self._adaptive_memory.compute(sv)
        self._ambient_factor = self._ambient_corrector.compute_factor(self._current_ambient)
        self._apply_learned_to_cfg()

    def _apply_learned_to_cfg(self) -> None:
        """
        Applique les corrections apprises sur cfg.
        Les valeurs de base (définies dans PIDConfig) ne sont pas écrasées :
        on stocke les valeurs ajustées dans des attributs séparés préfixés `_adj_`.
        """
        if self._learned is None:
            return
        lp = self._learned

        base_burner = self.cfg.max_burner

        # The control law consumes P_ss and lead_sec (see load_law_params); here we
        # only keep the burner-ceiling adjustment, clamped DOWN by effective_max_burner().
        self._adj_max_burner = max(40.0, min(100.0,
            base_burner + lp.max_burner_adj))

        _logd.debug(
            f"Paramètres adaptatifs [conf={lp.confidence:.2f}, n={lp.n_samples}]: "
            f"burner={self._adj_max_burner:.1f}% (base={base_burner:.1f}%) | "
            f"ambient_factor={self._ambient_factor:.3f}"
        )

    # ── Méthodes à appeler depuis TilauPreheatPID ──────────────────────────
    # ── Cross-roast control-law persistence (P_ss + lead_sec) ─────────

    def _law_context(self) -> tuple[str, str]:
        """Return the stable machine/source identity used to isolate learned state."""
        scanner = getattr(self, "_alog_scanner", None)
        machine = getattr(scanner, "machine_fingerprint", "")
        channel = getattr(scanner, "control_channel", None)
        if not machine:
            qmc = getattr(getattr(self, "aw", None), "qmc", None)
            machine = _normalise_identity(
                getattr(qmc, "roastertype_setup", "")
                or getattr(qmc, "roastertype", "")
                or getattr(qmc, "machinesetup", "")
            )
        if channel is None:
            source = getattr(getattr(getattr(self, "aw", None), "pidcontrol", None),
                             "pidSource", 1)
            channel = AlogScanner._control_channel(source)
        return machine or "unknown", channel

    def _law_context_prefix(self, version: int | None = None) -> str:
        machine, channel = self._law_context()
        return f"tilaupid/v{version or self._LAW_VERSION}/{machine}/{channel}"

    @staticmethod
    def _law_sv_token(sv: float) -> int:
        """Lossless-for-UI node key at 0.1°C precision, without locale punctuation."""
        return int(round(float(sv) * 10.0))

    def _law_key_prefix(self, sv: float | None = None) -> str:
        target = self.cfg.target_sv if sv is None else sv
        return f"{self._law_context_prefix()}/nodes/sv_{self._law_sv_token(target)}"

    def _law_param_keys(self, sv: float | None = None) -> tuple[str, str]:
        """Contextual exact-SV node keys for independent P_ss/lead learning."""
        prefix = self._law_key_prefix(sv)
        return f"{prefix}/p_ss", f"{prefix}/lead"

    def _law_nodes(self, settings: QSettings) -> list[tuple[float, float, float, str]]:
        """Return valid learned nodes as (SV, P_ss, lead, prefix), sorted by SV."""
        root = f"{self._law_context_prefix()}/nodes/sv_"
        nodes: list[tuple[float, float, float, str]] = []
        for key in settings.allKeys():
            if not key.startswith(root) or not key.endswith("/p_ss"):
                continue
            prefix = key[:-len("/p_ss")]
            token_text = prefix[len(root):]
            try:
                sv = int(token_text) / 10.0
                p_ss = float(settings.value(key, 0.0, float))
                lead = float(settings.value(f"{prefix}/lead", 0.0, float))
            except (TypeError, ValueError):
                continue
            if (50.0 <= sv <= 350.0
                    and math.isfinite(p_ss)
                    and math.isfinite(lead)
                    and settings.contains(f"{prefix}/lead")):
                nodes.append((sv, p_ss, lead, prefix))
        return sorted(nodes, key=lambda node: node[0])

    def _resolve_law_nodes(
        self,
        settings: QSettings,
        sv: float,
    ) -> tuple[float | None, float | None, float, str, tuple[str, ...]]:
        """Resolve learned values plus their continuous blend weight.

        Exact and bracketed interpolation have weight 1. At an outer edge, or
        beside a node bounding an intentionally unbridged large gap, influence
        fades linearly to the physical/corpus fallback instead of introducing a
        new discontinuity at the safety distance.
        """
        nodes = self._law_nodes(settings)
        if not nodes:
            return None, None, 0.0, "seed/default", ()

        for node_sv, p_ss, lead, prefix in nodes:
            if math.isclose(node_sv, sv, abs_tol=0.05):
                return p_ss, lead, 1.0, f"learned@{node_sv:.1f}°C", (prefix,)

        def edge_blend(
            node: tuple[float, float, float, str],
        ) -> tuple[float | None, float | None, float, str, tuple[str, ...]]:
            distance = abs(sv - node[0])
            weight = max(0.0, 1.0 - distance / self._LAW_EDGE_MAX_DISTANCE_C)
            if weight <= 0.0:
                return None, None, 0.0, "seed/default", ()
            provenance = f"edge-blend@{node[0]:.1f}°C:{weight:.0%}"
            return node[1], node[2], weight, provenance, (node[3],)

        if sv < nodes[0][0]:
            return edge_blend(nodes[0])
        if sv > nodes[-1][0]:
            return edge_blend(nodes[-1])

        lower = max((node for node in nodes if node[0] < sv), key=lambda node: node[0])
        upper = min((node for node in nodes if node[0] > sv), key=lambda node: node[0])
        gap = upper[0] - lower[0]
        if gap <= 0.0:
            return None, None, 0.0, "seed/default", ()
        if gap > self._LAW_MAX_INTERPOLATION_GAP_C:
            nearest = min((lower, upper), key=lambda node: abs(sv - node[0]))
            return edge_blend(nearest)
        ratio = (sv - lower[0]) / gap
        p_ss = lower[1] + ratio * (upper[1] - lower[1])
        lead = lower[2] + ratio * (upper[2] - lower[2])
        provenance = f"interpolated:{lower[0]:.1f}↔{upper[0]:.1f}°C"
        return p_ss, lead, 1.0, provenance, (lower[3], upper[3])

    def _migrate_persisted_law(self) -> None:
        """One-shot migration marker for the current persisted-law layout.

        Obsolete relay-law integrators are removed. Contextual v3 10°C buckets
        are copied to equivalent v4 exact-SV nodes, including their audit metadata;
        v3 keys remain untouched for rollback/audit purposes.
        Idempotent; gated by a stored law_version.
        Never writes under the simulator so a simulated run can't stamp the
        version and skip a real migration."""
        if getattr(getattr(self, "aw", None), "simulator", None) is not None:
            return
        s = QSettings()
        try:
            ver = int(s.value("tilaupid/law_version", 0, int) or 0)
        except (TypeError, ValueError):
            ver = 0
        if ver >= self._LAW_VERSION:
            return
        all_keys = list(s.allKeys())
        removed = 0
        for key in all_keys:
            if key.startswith("tilaupid/zone_integrator_"):
                s.remove(key)
                removed += 1

        migrated = 0
        v3_prefixes = {
            key[:-len("/p_ss")]
            for key in all_keys
            if key.startswith("tilaupid/v3/") and key.endswith("/p_ss")
        }
        for old_prefix in v3_prefixes:
            parts = old_prefix.split("/")
            if (len(parts) != 5
                    or parts[0] != "tilaupid"
                    or parts[1] != "v3"
                    or not parts[4].startswith("sv_")
                    or not s.contains(f"{old_prefix}/lead")):
                continue
            try:
                old_sv = float(parts[4][len("sv_"):])
            except ValueError:
                continue
            new_prefix = (
                f"tilaupid/v4/{parts[2]}/{parts[3]}/nodes/"
                f"sv_{self._law_sv_token(old_sv)}"
            )
            for old_key in all_keys:
                marker = f"{old_prefix}/"
                if not old_key.startswith(marker):
                    continue
                new_key = f"{new_prefix}/{old_key[len(marker):]}"
                if not s.contains(new_key):
                    s.setValue(new_key, s.value(old_key))
            migrated += 1
        s.setValue("tilaupid/law_version", int(self._LAW_VERSION))
        _logd.debug(f"TilauPID: migrated to law v{self._LAW_VERSION} "
                    f"({migrated} v3 node(s) copied, "
                    f"{removed} stale integrator bucket(s) purged)")

    def law_corpus_summary(self, sv: float) -> dict:
        """Read-only aggregate of what the loaded alog corpus says about the preheat
        near a given SV. Powers both the start-up diagnostic log and the offline
        tools/analysis report — no side effects, no persistence.

        Returns counts, the calibration-gated median hold power (P_ss candidate),
        the mean overshoot (lead candidate) and the observed ramp RoR (the
        "how the fire drove the rise" number the operator asked about).
        """
        hist = list(self._adaptive_memory._history)
        near = [m for m in hist if abs(m.target_sv - sv) <= self._SEED_SV_WINDOW_C]
        # "held" = the roast reached SV and logged burner-channel power during the hold.
        # Extraction only admits marked PID preheats now, so every metric here targeted a
        # real recorded SV and its overshoot is meaningful.
        held = [m for m in near if m.was_stable and m.hold_mean_power > 0]
        # P_ss candidates: held roasts recorded AFTER the burner recalibration only.
        calib = [m for m in held if m.timestamp >= self._SEED_CALIB_CUTOFF_EPOCH]
        # Overshoot/lead candidates. target_is_recorded_sv is True for every extracted
        # metric today, so this equals `held`; the filter stays as a defensive guard.
        held_recorded = [m for m in held if getattr(m, "target_is_recorded_sv", False)]
        ramps = [m.mean_ramp_ror for m in near if m.mean_ramp_ror > 0]
        return {
            "sv": sv,
            "n_near": len(near),
            "n_held": len(held),
            "n_held_calibrated": len(calib),
            "n_held_recorded": len(held_recorded),
            "p_ss_median": (median(m.hold_mean_power for m in calib) if calib else None),
            # Overshoot only from recorded-SV holds (see held_recorded rationale above).
            "mean_overshoot_c": (mean(m.overshoot_c for m in held_recorded) if held_recorded else None),
            "mean_ramp_ror": (mean(ramps) if ramps else None),
            "peak_ramp_ror": (max((m.peak_ramp_ror for m in near), default=None)),
        }

    def _seed_law_params_from_history(self) -> tuple[Optional[float], Optional[float]]:
        """Derive a cold-start (P_ss, lead_sec) from the corpus, or (None, None) per
        knob when there is not enough trustworthy data. Never persists."""
        summ = self.law_corpus_summary(self.cfg.target_sv)

        p_ss_seed: Optional[float] = None
        if summ["n_held_calibrated"] >= self._SEED_MIN_ROASTS and summ["p_ss_median"] is not None:
            p_ss_seed = float(summ["p_ss_median"])

        lead_seed: Optional[float] = None
        # Lead seeds from measured overshoot, only defined for recorded-SV holds; stays
        # at the safe default until enough real PID preheats accumulate.
        if summ["n_held_recorded"] >= self._SEED_MIN_ROASTS and summ["mean_overshoot_c"] is not None:
            excess = max(0.0, summ["mean_overshoot_c"] - self._OVERSHOOT_DEADBAND_C)
            lead_seed = self.cfg.lead_sec_default + self._SEED_LEAD_OVERSHOOT_GAIN * excess

        return p_ss_seed, lead_seed

    def load_law_params(self) -> tuple[float, float]:
        """Return continuously resolved (P_ss, lead_sec), clamped to safe ranges.

        Priority per knob: exact/interpolated learned nodes (real roasts) → a corpus
        seed (historical alogs) → the physical/config default. Reads never write and
        the simulator never persists, so a simulated preheat remains a safe dry-run.
        """
        self._migrate_persisted_law()
        s = QSettings()
        learned_p_ss, learned_lead, learned_weight, _source, _prefixes = self._resolve_law_nodes(
            s, self.cfg.target_sv)

        seed_p_ss, seed_lead = self._seed_law_params_from_history()
        thermal_p_ss, thermal_lead = self._thermal_prior_params()

        # Defaults when no seed: physical hold estimate for P_ss (_base_hold_power ≈
        # 18 + SV/9.5), config for lead. A shadow-promoted offline model sits between
        # direct corpus evidence and the physical default; exact/interpolated law nodes win.
        base_hold = getattr(self, "_base_hold_power", self.cfg.p_ss_default)
        default_p_ss = (
            seed_p_ss if seed_p_ss is not None
            else thermal_p_ss if thermal_p_ss is not None
            else float(base_hold)
        )
        default_lead = (
            seed_lead if seed_lead is not None
            else thermal_lead if thermal_lead is not None
            else self.cfg.lead_sec_default
        )

        p_ss = (
            default_p_ss + learned_weight * (learned_p_ss - default_p_ss)
            if learned_p_ss is not None else default_p_ss
        )
        lead = (
            default_lead + learned_weight * (learned_lead - default_lead)
            if learned_lead is not None else default_lead
        )
        p_ss = max(self._PSS_MIN, min(self.effective_max_burner(), p_ss))
        lead = max(self.cfg.lead_sec_min, min(self.cfg.lead_sec_max, lead))
        return p_ss, lead

    def format_law_diagnostic(self) -> str:
        """One-line human summary of the corpus + resolved params for the start-up log."""
        sv = self.cfg.target_sv
        summ = self.law_corpus_summary(sv)
        s = QSettings()
        _p_ss, _lead, _weight, learned, prefixes = self._resolve_law_nodes(s, sv)
        updates = 0
        for prefix in prefixes:
            try:
                updates += int(s.value(f"{prefix}/n_updates", 0, int) or 0)
            except (TypeError, ValueError):
                continue
        if len(prefixes) == 1:
            last_evidence = str(
                s.value(f"{prefixes[0]}/last_evidence", "none") or "none")
        elif len(prefixes) > 1:
            last_evidence = "linear"
        else:
            last_evidence = "none"
        pss_med = summ["p_ss_median"]
        mo = summ["mean_overshoot_c"]
        rr = summ["mean_ramp_ror"]
        thermal = getattr(self, "_thermal_candidate", None)
        thermal_status = (
            f"active:{thermal.fingerprint}" if thermal is not None and self._thermal_active
            else f"shadow:{thermal.fingerprint}" if thermal is not None
            else "none"
        )
        return (
            f"PID corpus @SV={sv:.1f}°C [{learned}; updates={updates}; "
            f"last={last_evidence}; thermal={thermal_status}] | "
            f"roasts near={summ['n_near']} held={summ['n_held']} "
            f"calibrated={summ['n_held_calibrated']} | "
            f"hold_median={'n/a' if pss_med is None else f'{pss_med:.1f}%'} "
            f"overshoot_mean={'n/a' if mo is None else f'{mo:.1f}°C'} "
            f"ramp_mean={'n/a' if rr is None else f'{rr:.1f}°C/min'} "
            f"→ P_ss={self.p_ss:.1f}% lead={self.lead_sec:.1f}s"
        )

    @staticmethod
    def _setting_float(settings: QSettings, key: str, default: float) -> float:
        try:
            return float(settings.value(key, default, float))
        except (TypeError, ValueError):
            return default

    def _save_law_params(self, p_ss: float, lead: float, evidence: str) -> None:
        """Persist a qualified update with enough metadata to audit or roll it back.

        Never writes under the simulator (a simulated preheat must not train the
        real controller).
        """
        if getattr(getattr(self, "aw", None), "simulator", None) is not None:
            return
        s = QSettings()
        k_pss, k_lead = self._law_param_keys()
        prefix = self._law_key_prefix()
        if s.contains(k_pss) and s.contains(k_lead):
            s.setValue(f"{prefix}/previous_p_ss", self._setting_float(s, k_pss, p_ss))
            s.setValue(f"{prefix}/previous_lead", self._setting_float(s, k_lead, lead))
        else:
            s.remove(f"{prefix}/previous_p_ss")
            s.remove(f"{prefix}/previous_lead")

        try:
            old_n = int(s.value(f"{prefix}/n_updates", 0, int) or 0)
        except (TypeError, ValueError):
            old_n = 0
        new_n = max(0, old_n) + 1
        for name, value in (("p_ss", p_ss), ("lead", lead)):
            old_mean = self._setting_float(s, f"{prefix}/{name}_mean", value)
            old_m2 = self._setting_float(s, f"{prefix}/{name}_m2", 0.0)
            if old_n <= 0:
                new_mean, new_m2 = value, 0.0
            else:
                delta = value - old_mean
                new_mean = old_mean + delta / new_n
                new_m2 = old_m2 + delta * (value - new_mean)
            s.setValue(f"{prefix}/{name}_mean", float(new_mean))
            s.setValue(f"{prefix}/{name}_m2", float(max(0.0, new_m2)))
        s.setValue(k_pss, float(p_ss))
        s.setValue(k_lead, float(lead))
        s.setValue(f"{prefix}/n_updates", new_n)
        s.setValue(f"{prefix}/updated_epoch", float(time.time()))
        s.setValue(f"{prefix}/last_evidence", evidence)

    def rollback_law_params(self) -> bool:
        """Restore the immediately preceding qualified update for this context."""
        if getattr(getattr(self, "aw", None), "simulator", None) is not None:
            return False
        s = QSettings()
        prefix = self._law_key_prefix()
        previous_p_ss = f"{prefix}/previous_p_ss"
        previous_lead = f"{prefix}/previous_lead"
        if not s.contains(previous_p_ss) or not s.contains(previous_lead):
            return False
        k_pss, k_lead = self._law_param_keys()
        s.setValue(k_pss, self._setting_float(s, previous_p_ss, self.cfg.p_ss_default))
        s.setValue(k_lead, self._setting_float(s, previous_lead, self.cfg.lead_sec_default))
        s.remove(previous_p_ss)
        s.remove(previous_lead)
        s.setValue(f"{prefix}/last_evidence", "rollback")
        s.setValue(f"{prefix}/updated_epoch", float(time.time()))
        return True

    def adaptive_start(self, ambient: Optional[AmbientConditions] = None) -> None:
        """
        À appeler depuis start() de TilauPreheatPID, APRÈS l'init de session.
        Réutilise l'historique déjà chargé par le gestionnaire et met à jour les
        conditions ambiantes. Un changement explicite de machine ou de source
        BT/ET est le seul cas qui impose un nouveau chargement borné.
        """
        if ambient is not None:
            self._current_ambient = ambient
        self._session_rors.clear()
        self._session_burner_hold.clear()
        self._session_hold_samples.clear()
        self._session_start_time = time.perf_counter()
        self._session_reached_sv = False
        self._session_reach_time = 0.0
        self._session_max_bt = 0.0
        self._session_filtered_max_bt = 0.0
        self._session_temp_filter.clear()
        self._session_hold_started_at = None
        self._session_hold_last_at = None
        # Never let the previous preheat's plateau qualify the new
        # session or bias its terminal P_ss estimate.
        self._stabilisation_detector.reset()
        # Point de jointure unique : le worker lancé au ON a normalement fini
        # bien avant le START. Sinon on l'attend ici, pas au clic ON.
        self._ensure_history_loaded()
        context_changed = self._refresh_learning_context()
        # START is a real-time command: never rescan the archive when
        # the manager already loaded this exact machine/input context.
        if context_changed:
            self._load_history()
        else:
            self._refresh_learned()
            _logd.debug("TilauPID: historique adaptatif réutilisé en mémoire au START")
        # Loading the offline sidecar is constant work (one small JSON),
        # then the observer is reset for this session. It never scans alogs here.
        self._load_thermal_candidate()
        # NOTE: learned P_ss/lead are (re)loaded by TilauPreheatPID.start() via
        # load_law_params(), resolved continuously at the current SV — nothing to do here.

    def get_learned_thermal_model(
        self,
        target_sv: float,
        kernel_type: str = "triangular",
        kernel_sigma: float = 1.0
    ) -> ThermalModel:
        """
        Query learned thermal characteristics for this roaster at given target + current ambient.

        Uses weighted kernel aggregation from historical roasts:
        - kernel_type: "triangular" (FIR) or "gaussian" (inertia)
        - kernel_sigma: Gaussian σ (only for gaussian kernel)

        Called from TilauPreheatPID.start() to initialize thermal model parameters.
        """
        self._ensure_history_loaded()
        return self._adaptive_memory.get_thermal_characteristics(
            target_sv=target_sv,
            ambient=self._current_ambient,
            kernel_type=kernel_type,
            kernel_sigma=kernel_sigma
        )

    def _on_cycle(self, t_c: float, ror_c_per_min: float, burner: int) -> None:
        """
        À appeler depuis cycle() de TilauPreheatPID après compute_fuzzy_power.

        t_c           : température actuelle en °C (interne)
        ror_c_per_min : RoR courant en °C/min
        burner        : puissance brûleur envoyée (%)
        """
        sv_c = self.cfg.target_sv
        now = time.perf_counter()
        # Shadow failures must be observational only: a candidate bug can
        # disable its own validation, but can neither alter nor trip the live PID.
        shadow = getattr(self, "_thermal_shadow", None)
        if shadow is not None:
            try:
                shadow.observe(
                    now=now,
                    temperature_c=t_c,
                    burner_pct=float(burner),
                    ambient_c=self._current_ambient.temp_ambient,
                )
            except Exception:  # noqa: BLE001 - strict isolation from the control path
                self._thermal_shadow = None
                _logd.exception("Thermal shadow disabled after observer error")
        self._session_max_bt = max(getattr(self, '_session_max_bt', 0.0), t_c)
        self._session_temp_filter.append(t_c)
        filtered_t = float(median(self._session_temp_filter))
        self._session_filtered_max_bt = max(
            getattr(self, '_session_filtered_max_bt', 0.0), filtered_t)

        # Accumulation des métriques de session
        if ror_c_per_min > 0:
            self._session_rors.append(ror_c_per_min)

        # Détection du premier passage à SV
        if not self._session_reached_sv and filtered_t >= sv_c - 1.0:
            self._session_reached_sv = True
            self._session_reach_time = now
            _logd.debug(f"Session: SV atteinte ({filtered_t:.1f}°C filtré)")

        # Accumulation puissance hold (après atteinte SV) — métrique legacy
        if self._session_reached_sv and burner > 0:
            self._session_burner_hold.append(float(burner))

        # P_ss learning sample: burner commanded while genuinely AT SV
        # (|t−SV| ≤ hold band). This is the steady power the drum actually needs
        # to hold, so learning it here closes the proportional droop cross-roast.
        if (self._session_reached_sv
                and abs(filtered_t - sv_c) <= self._HOLD_BAND_C
                and burner > 0):
            if self._session_hold_started_at is None:
                self._session_hold_samples.clear()
                self._session_hold_started_at = now
            self._session_hold_last_at = now
            self._session_hold_samples.append(float(burner))
        else:
            # P_ss represents a continuous equilibrium, not scattered visits to SV.
            self._session_hold_samples.clear()
            self._session_hold_started_at = None
            self._session_hold_last_at = None

        # Stabilisation
        self._stabilisation_detector.update(filtered_t, sv_c)
        slope = self._stabilisation_detector.slope_c_per_min()
        quality = self._stabilisation_detector.ramp_quality()
        hold_integral = float(getattr(
            getattr(self, "_hold_integrator", None), "correction", 0.0))

        if self._stabilisation_detector.is_stable(min_duration_sec=15.0):
            _logd.debug(
                f"STABLE | T={t_c:.2f}°C SV={sv_c:.1f}°C "
                f"pente={slope:+.2f}°C/min {quality} I_hold={hold_integral:+.2f}% "
                f"depuis {self._stabilisation_detector.seconds_stable:.0f}s"
            )
        else:
            _logd.debug(
                f"T={t_c:.2f}°C | pente={slope:+.2f}°C/min | {quality} | "
                f"I_hold={hold_integral:+.2f}% | "
                f"stable={self._stabilisation_detector.seconds_stable:.0f}s"
            )

    def _learn_law_params(self) -> bool:
        """Refine the two live control knobs (P_ss, lead_sec) from this session and
        persist them per-SV. Split out from metric bookkeeping so it runs on every
        completed preheat, including one that fell short of SV.

          lead_sec — overshoot beyond deadband ⇒ lengthen (brake earlier); a real
                     approach that still fell short of SV ⇒ shorten (brake later).
                     Clamped [lead_min, lead_max].
          P_ss     — on any quasi-flat tail within _SETTLE_PROXIMITY_C of SV: EMA toward
                     the (ambient-neutralised) measured hold if it held within ±0.5°C,
                     else a droop nudge toward SV. Corrects BOTH a hot park and a cold
                     droop. Clamped [P_ss_min, max_burner].
        """
        now = time.perf_counter()
        session_duration = now - self._session_start_time
        if session_duration < self._MIN_LEARNING_SESSION_SEC:
            _logd.debug(
                f"Law learn ignored: session too short ({session_duration:.1f}s < "
                f"{self._MIN_LEARNING_SESSION_SEC:.0f}s)")
            return False

        sv = self.cfg.target_sv
        max_bt = getattr(self, "_session_filtered_max_bt", 0.0)
        overshoot = max(0.0, max_bt - sv)
        reached = self._session_reached_sv
        approached = max_bt >= sv - self._APPROACH_MIN_C   # got within 10°C of SV at least
        t_settle = self._stabilisation_detector.mean_temp()
        slope = self._stabilisation_detector.slope_c_per_min()
        # A quasi-flat tail near SV is a settle point whether it settled on SV or parked
        # hot/cold. Gate is slope + proximity, not `reached`: a drum with P_ss too low settles below SV without tripping it.
        settled = (self._stabilisation_detector.has_full_window()
                   and t_settle is not None
                   and abs(slope) <= 2.0
                   and abs(t_settle - sv) <= self._SETTLE_PROXIMITY_C)

        old_p_ss = float(getattr(self, "p_ss", self.cfg.p_ss_default))
        old_lead = float(getattr(self, "lead_sec", self.cfg.lead_sec_default))
        p_ss = old_p_ss
        lead = old_lead
        evidence: list[str] = []

        # ── lead_sec (projection lead ↔ transient overshoot) ──────────
        # Only learn from a roast that actually ran an approach: an early abort far
        # below SV must not ratchet the lead down on no real data.
        post_reach = now - self._session_reach_time if reached else 0.0
        if (overshoot > self._OVERSHOOT_DEADBAND_C
                and post_reach >= self._MIN_POST_REACH_SEC):
            lead += self._LEAD_OVERSHOOT_GAIN * (overshoot - self._OVERSHOOT_DEADBAND_C)
            evidence.append("overshoot")
        elif approached and not reached:
            lead -= self._LEAD_UNDERSHOOT_STEP
            evidence.append("undershoot")

        # ── P_ss (steady hold ↔ proportional droop) ───────────────────
        if settled:
            assert t_settle is not None  # narrowed by `settled`; keeps static analysis explicit
            hold_dwell = (
                self._session_hold_last_at - self._session_hold_started_at
                if self._session_hold_started_at is not None
                and self._session_hold_last_at is not None else 0.0
            )
            qualified_hold = (
                hold_dwell >= self._MIN_HOLD_DWELL_SEC
                and len(self._session_hold_samples) >= self._MIN_HOLD_SAMPLES
            )
            if (abs(t_settle - sv) <= self._SETTLE_BAND_C
                    and qualified_hold):
                # Held cleanly at SV → trust the measured steady power. Neutralise the
                # ambient factor: the law commands P_ss·ambient_factor, so learning from
                # the raw commanded burner would re-apply the factor a second time.
                af = self._ambient_factor if self._ambient_factor > 1e-6 else 1.0
                measured = float(median(self._session_hold_samples)) / af
                p_ss = (1.0 - self._PSS_EMA_ALPHA) * p_ss + self._PSS_EMA_ALPHA * measured
                evidence.append("stable_hold")
            elif abs(t_settle - sv) > self._SETTLE_BAND_C:
                # Parked off SV (droop): +err raises hold if cold, lowers it if hot.
                p_ss += self._PSS_DROOP_GAIN * (sv - t_settle)
                evidence.append("settled_droop")

        # One roast may inform the controller, but may never dominate it.
        p_ss = max(old_p_ss - self._MAX_PSS_STEP,
                   min(old_p_ss + self._MAX_PSS_STEP, p_ss))
        lead = max(old_lead - self._MAX_LEAD_STEP,
                   min(old_lead + self._MAX_LEAD_STEP, lead))
        p_ss = max(self._PSS_MIN, min(self.effective_max_burner(), p_ss))
        lead = max(self.cfg.lead_sec_min, min(self.cfg.lead_sec_max, lead))

        if not evidence or (math.isclose(p_ss, old_p_ss) and math.isclose(lead, old_lead)):
            _logd.debug("Law learn ignored: no qualified parameter evidence.")
            return False

        self.p_ss, self.lead_sec = p_ss, lead
        evidence_text = "+".join(evidence)
        self._save_law_params(p_ss, lead, evidence_text)
        _logd.debug(
            f"Law learn [{evidence_text}]: overshoot={overshoot:.1f}°C reached={reached} "
            f"slope={slope:+.2f}°C/min t_settle={t_settle} → P_ss={p_ss:.1f}% lead={lead:.1f}s"
        )
        return True

    def _on_preheat_complete(self) -> None:
        """
        À appeler à la fin de la phase de préchauffe (stop ou stabilisation confirmée).
        Apprend les paramètres de loi (P_ss/lead) et pousse les métriques de session.
        """
        # En simulation, on n'apprend rien : ni métrique poussée, ni paramètre sauvé.
        # Évite qu'un préchauffage simulé n'entraîne le PID réel.
        if getattr(getattr(self, "aw", None), "simulator", None) is not None:
            _logd.debug("Préchauffage simulé — apprentissage PID ignoré (aucun stockage).")
            return

        # Score the offline candidate before any live-law learning. The
        # observer only saw measured temperature + the burner chosen by the existing
        # controller; promotion affects the next START at the earliest.
        try:
            self._finish_thermal_shadow()
        except Exception:  # noqa: BLE001 - shadow can never block normal PID learning
            _logd.exception("Thermal shadow result ignored after scoring error")

        # Learn the live control knobs first — this runs even when SV was
        # never reached, so an undershooting roast still shortens the brake lead.
        self._learn_law_params()

        if not self._session_reached_sv:
            _logd.debug("Session incomplète (SV jamais atteinte) — métriques non poussées.")
            return

        reach_sec = self._session_reach_time - self._session_start_time

        m = RoastPreheatMetrics(
            # Wall-clock epoch (NOT perf_counter) so this session's own roast sits on the
            # same time axis as the calibration cutoff and the alog mtimes it is compared to.
            timestamp=time.time(),
            target_sv=self.cfg.target_sv,
            ambient=self._current_ambient,
            mean_ramp_ror=mean(self._session_rors) if self._session_rors else 0.0,
            peak_ramp_ror=max(self._session_rors) if self._session_rors else 0.0,
            overshoot_c=max(
                0.0,
                getattr(self, '_session_filtered_max_bt', 0.0) - self.cfg.target_sv,
            ),
            time_to_sv_sec=reach_sec,
            stabilise_time_sec=self._stabilisation_detector.seconds_stable,
            hold_mean_power=(
                float(median(self._session_hold_samples))
                if (self._session_hold_started_at is not None
                    and self._session_hold_last_at is not None
                    and self._session_hold_last_at - self._session_hold_started_at
                    >= self._MIN_HOLD_DWELL_SEC
                    and len(self._session_hold_samples) >= self._MIN_HOLD_SAMPLES)
                else 0.0
            ),
            was_stable=self._stabilisation_detector.is_stable(10.0),
            # The live PID knows its own SV, so this session's overshoot (max_bt − target_sv)
            # is a genuine recorded-SV overshoot and SHOULD train the lead seed. It also
            # commands its own burner, so hold_mean_power is trustworthy (channel-equivalent).
            target_is_recorded_sv=True,
            had_burner_channel=True,
            max_burner_used=self.effective_max_burner(),
            base_hold_power_used=float(getattr(self, "p_ss", self.cfg.p_ss_default)),
        )
        self._adaptive_memory.push(m)
        _logd.debug(
            f"Session apprise: RoR moy={m.mean_ramp_ror:.1f}°C/min "
            f"time_to_sv={m.time_to_sv_sec:.0f}s hold={m.hold_mean_power:.1f}% "
            f"stable={m.was_stable}"
        )

    def effective_max_burner(self) -> float:
        # cfg.max_burner is a HARD safety ceiling: the learned adjustment may only
        # pull the burner DOWN, never above the configured cap.
        return min(self.cfg.max_burner,
                   getattr(self, "_adj_max_burner", self.cfg.max_burner))

    def update_ambient(self, temp: float, humidity: float, pressure: float) -> None:
        """Met à jour les conditions ambiantes depuis les variables de scope."""
        self._current_ambient = AmbientConditions(
            temp_ambient=temp,
            humidity=humidity,
            pressure=pressure,
        )
        # Recalcule le facteur ambiant immédiatement
        self._ambient_factor = self._ambient_corrector.compute_factor(self._current_ambient)
        _logd.debug(
            f"Conditions ambiantes mises à jour: "
            f"T={temp:.1f}°C HR={humidity:.0f}% P={pressure:.0f}hPa "
            f"→ facteur={self._ambient_factor:.3f}"
        )

    def adaptive_status(self) -> dict:
        """Retourne un résumé de l'état adaptatif (pour debug / TilauScope)."""
        lp = self._learned or LearnedParams()
        return {
            "n_samples": lp.n_samples,
            "confidence": round(lp.confidence, 2),
            "zone_adj": round(lp.zone_fuzzy_start_adj, 4),
            "coast_adj": round(lp.coast_lookahead_adj, 2),
            "burner_adj": round(lp.max_burner_adj, 2),
            "hold_override": lp.hold_power_override,
            "ambient_factor": round(self._ambient_factor, 4),
            "hold_integral_pct": round(float(getattr(
                getattr(self, "_hold_integrator", None), "correction", 0.0)), 2),
            "is_stable": self._stabilisation_detector.is_stable(),
            "stable_since": round(self._stabilisation_detector.seconds_stable, 1),
            "slope_c_per_min": round(self._stabilisation_detector.slope_c_per_min(), 2),
            "ramp_quality": self._stabilisation_detector.ramp_quality(),
        }

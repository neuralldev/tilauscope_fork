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

## TILAU ## Lazy annotations so this module can be imported by an offline corpus
## analysis tool WITHOUT importing artisanlib.main (which would bind a QApplication
## and clobber the user's real Artisan prefs). ApplicationWindow / ProfileData are
## used only in type hints + a string cast, so they live under TYPE_CHECKING.
from __future__ import annotations

import logging
import time
import math
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, median, stdev
from typing import List, Optional, Callable, TYPE_CHECKING
import ast  # Import de la bibliothèque ast
from typing import cast, Final

## TILAU ## Pure event-value conversion (internal→external %). Lives in artisanlib.util,
## which is safe to import at runtime (no QApplication, no prefs binding) — unlike
## artisanlib.main. This lets the alog scanner extract hold power WITHOUT an aw handle,
## so the offline corpus tool gets the same numbers as the live PID.
from artisanlib.util import events_internal_to_external_value, fromFtoCstrict

if TYPE_CHECKING:
    from artisanlib.atypes import ProfileData
    from artisanlib.main import ApplicationWindow

from PyQt6.QtCore import QSettings

_logd: Final[logging.Logger] = logging.getLogger("tilau")

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
    # True when target_sv came from a real recorded SV event ("TilauPID Preheat started").
    # Extraction now requires that marker (unmarked roasts = manual preheat, skipped), so
    # every extracted metric sets this True; the field remains as an explicit invariant and
    # guards any downstream reader against a future non-recorded source being reintroduced.
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

    def __init__(self, alog_dir: str, window: int = 10, aw:ApplicationWindow | None = None):
        self.alog_dir = Path(alog_dir)
        self.window = window
        self.aw = aw

    def _list_recent(self) -> List[Path]:
        """Retourne les `window` alogs les plus récents (tri par mtime)."""
        if not self.alog_dir.exists():
            _logd.warning(f"Répertoire alog introuvable : {self.alog_dir}")
            return []
        files = sorted(
            self.alog_dir.glob(self.ALOG_GLOB),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )
        return files[: self.window]

    def _extract_metrics(self, path: Path, params:RoastPreheatMetrics|None = None) -> RoastPreheatMetrics|None:
        """Parse un alog et retourne les métriques de préchauffe, ou None si absent."""
        try:
            ## TILAU ## An .alog is a repr()'d Python dict — feed it straight to
            ## literal_eval. The former codecs.decode(..., 'unicode_escape') turned the
            ## \n escapes inside multi-line 'beans' text into RAW newlines, producing an
            ## unterminated-string SyntaxError: it silently dropped ~97% of real roasts
            ## (only 3/92 here parsed), starving the cross-roast learning. literal_eval
            ## already handles \uXXXX / \n escapes natively.
            try:
                text = path.read_text(encoding='utf-8')
            except UnicodeDecodeError:
                text = path.read_bytes().decode('latin-1')
            data = cast('ProfileData', ast.literal_eval(text))
        except Exception as exc:
            _logd.debug(f"Impossible de lire {path.name}: {exc}")
            return None

        ## TILAU ## skip profiles recorded under the Simulator — a simulated roast
        ## (even if accidentally saved) must never train the cross-roast PID.
        if isinstance(data, dict) and data.get('tilau_simulated'):
            _logd.debug(f"{path.name}: profil simulé — ignoré pour l'apprentissage PID")
            return None

        if params is None:
            params = RoastPreheatMetrics()

        # ── Conditions ambiantes ──────────────────────────────────────────
        ambient = AmbientConditions(
            temp_ambient=data.get("ambientTemp", 20.0),
            humidity=data.get("ambient_humidity", 50.0),
            pressure=data.get("ambient_pressure", 1013.25),
        )

        # ── Série temporelle ─────────────────────────────────────────────
        timex: List[float] = data.get("timex", [])
        timeindex: List[int] = data.get("timeindex", [])
        # Channel the preheat PID actually followed in this roast — mirrors cycle():
        # BT=temp2 when pidSource in {0,1}, else ET=temp1. pidSource is persisted in the
        # alog (main.py writes profile['pidSource']); default to BT for legacy alogs.
        # NOTE: Artisan convention is temp1=ET, temp2=BT (do not swap these).
        pid_source = int(data.get("pidSource", 1) or 1)
        ctrl_raw: List[float] = data.get("temp2", []) if pid_source in (0, 1) else data.get("temp1", [])
        charge:int = timeindex[0] if (timeindex and timeindex[0] >= 0 ) else len(timex)-1 # charge index into timex

        ## TILAU ## An .alog is stored in the unit it was RECORDED in (data['mode'],
        ## 'C' or 'F') — Artisan converts only on load. All PID/seed maths is in °C, so
        ## an °F-recorded roast must be converted here or its temps land ~1.8× off. °C
        ## roasts (the common case) take the identity path and are byte-for-byte unchanged.
        ## NOTE: target_sv is resolved LATER (after the preheat window is known), NOT from
        ## svValues — svValues is Artisan's length-8 preset-BUTTON array, not a time series;
        ## max() returned a stored preset (e.g. 185) and mis-bucketed 87/92 corpus roasts.
        mode = str(data.get("mode", "C")).upper()
        if mode == "F":
            # Convert real readings only; preserve Artisan's -1 dropped-sample sentinel
            # (a raw -1 stays -1 in the °C path too, and nothing downstream reads it — but
            # keeping the invariant identical across units avoids a spurious divergence).
            ctrl_temp: List[float] = [v if v == -1 else fromFtoCstrict(v) for v in ctrl_raw]
        else:
            ctrl_temp = ctrl_raw

        if len(timex) < 10 or len(ctrl_temp) < 10:
            return None  # pas assez de données

        preheat_start_idx = None
        preheat_end_idx = None

        # ── Détection de la phase préchauffe : la clé °C d'abord, l'événement ensuite ──
        # A guided TilauPID preheat is proven by EITHER of two authoritative marks the app
        # writes when the PID runs — never by alarm strings (user-editable config):
        #   1. `tilau_preheat_sv_c` — the SV in °C, stamped by getProfile. PRIMARY source:
        #      no timex, no decode, no unit conversion. Present on all post-fix roasts.
        #   2. the type-4 "TilauPID Preheat started" special event — the on-graph marker,
        #      and the only source on legacy files repaired before the key existed. It also
        #      gives the precise preheat start index.
        # Neither present ⇒ the preheat was done by hand: not a valid learning base, skip.
        key_sv_c = data.get("tilau_preheat_sv_c")
        found_in_events = False
        recorded_sv_native: Optional[float] = None
        events_type = data.get("specialeventstype", [])
        events_strings = data.get("specialeventsStrings", [])
        events_value = data.get("specialeventsvalue", [])
        events_timex = data.get("specialevents", [])

        for k, ev in enumerate(events_type):
            if ev == 4 and events_strings[k] == "TilauPID Preheat started":  # type 4 pour les events de préchauffe
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
        i0, i1 = preheat_start_idx, preheat_end_idx
        t_slice = timex[i0: i1 + 1]
        ctrl_slice = ctrl_temp[i0: i1 + 1]

        if len(t_slice) < 3:
            return None

        # ── Cible (target_sv, °C) ─────────────────────────────────────────
        ## TILAU ## Prefer the explicit °C key (exact, already internal-unit); fall back to
        ## the event's native value converted via mode. Either way it is the real dialed
        ## setpoint, so overshoot (max_bt − SV) and the P_ss bucket key are both meaningful.
        if key_sv_c is not None:
            target_sv = float(key_sv_c)
        else:
            target_sv = fromFtoCstrict(recorded_sv_native) if mode == "F" else float(recorded_sv_native)

        # RoR de montée (approximation linéaire fenêtres de 3 points)
        rors = []
        for k in range(1, len(t_slice)):
            dt = t_slice[k] - t_slice[k - 1]
            if dt > 0:
                rors.append((ctrl_slice[k] - ctrl_slice[k - 1]) / (dt / 60.0))

        mean_ror = mean(rors) if rors else 0.0
        peak_ror = max(rors) if rors else 0.0

        # Dépassement / sous-dépassement mesurés contre la vraie SV enregistrée.
        max_bt = max((v for v in ctrl_slice if v != -1), default=target_sv)
        overshoot = max(0.0, max_bt - target_sv)
        undershoot = max(0.0, target_sv - max_bt)

        # Temps pour atteindre la cible ET l'index absolu correspondant. sv_reach_idx
        # borne le début de la phase de maintien (voir hold power) : premier point à
        # moins de 2°C sous la SV enregistrée.
        reach_thresh = target_sv - 2.0
        time_to_sv = 0.0
        sv_reach_idx: int | None = None
        for k, bt_val in enumerate(ctrl_slice):
            if bt_val != -1 and bt_val >= reach_thresh:
                time_to_sv = t_slice[k] - t_slice[0]
                sv_reach_idx = i0 + k          # index absolu dans timex
                break

        # Détection de stabilisation : variance sur les 30 dernières secondes
        hold_slice = [b for t_, b in zip(t_slice, ctrl_slice)
                      if t_ >= t_slice[-1] - 30]
        was_stable = False
        stabilise_extra = 0.0
        if len(hold_slice) >= 5:
            var = stdev(hold_slice) if len(hold_slice) > 1 else 99.0
            ## TILAU ## A flat plateau BELOW SV is a failed approach, not a hold — require
            ## both flatness (var < 0.8) AND tight proximity to the recorded SV (±0.8°C),
            ## so a hot-parked drum cannot certify itself as "stable".
            plateau_mean = mean(hold_slice)
            was_stable = var < 0.8 and abs(plateau_mean - target_sv) <= 0.8
            for k in range(5, len(t_slice)):
                window_bt = ctrl_slice[max(0, k - 5): k]
                if len(window_bt) > 1 and stdev(window_bt) < 0.8:
                    stabilise_extra = t_slice[k] - time_to_sv - t_slice[0]
                    break

        ## TILAU ## Puissance hold = le CANAL BRÛLEUR CONTINU (extra-device 'Burner'),
        ## PAS les événements spéciaux. Le flux d'events type-3 est trop épars : un maintien
        ## à plat n'émet aucun event, et le dernier event avant CHARGE est une valeur de
        ## RAMPE périmée (~90 %) — physiquement impossible comme puissance de maintien. Le
        ## canal continu (échantillonné à ~1 Hz, base de temps propre extratimex[i]) est la
        ## seule source fiable. Absent ⇒ pas de datapoint P_ss (hold_mean_pwr = 0 → non
        ## "held"), on retombe honnêtement sur le défaut physique plutôt qu'un chiffre fabriqué.
        burner = self._burner_channel(data)
        had_burner_channel = burner is not None
        hold_power_vals: list[float] = []
        if sv_reach_idx is not None and burner is not None:
            bvals, btimex = burner
            t_lo, t_hi = timex[sv_reach_idx], timex[i1]
            hold_power_vals = [
                float(bvals[j])
                for j in range(min(len(bvals), len(btimex)))
                if t_lo <= btimex[j] <= t_hi
                and isinstance(bvals[j], (int, float))
                and 0.0 < bvals[j] <= 100.0          # rejette -1 et valeurs aberrantes
            ]
        hold_mean_pwr = median(hold_power_vals) if hold_power_vals else 0.0

        ## TILAU ## Prefer the roast's own epoch for the burner-calibration gate: file
        ## mtime is bumped by any copy/backup/sync and would let a pre-Nov-2025 roast
        ## (doubled fire values) sneak past the cutoff and seed a 2× P_ss. Fall back to
        ## mtime only for legacy alogs with no roastepoch.
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
        results = []
        for p in self._list_recent():
            ## TILAU ## Fail-safe: a single malformed .alog (desynced special-events
            ## arrays, truncated/old format, hand-edited) must never abort the whole
            ## history load — which would propagate up through adaptive_start() and
            ## fail the preheat PID start. Skip the bad file and keep learning.
            try:
                m = self._extract_metrics(p)
            except Exception as exc:  # noqa: BLE001
                _logd.debug(f"AlogScanner: {p.name} ignoré (extraction impossible: {exc})")
                continue
            if m is not None:
                results.append(m)
        _logd.debug(f"AlogScanner: {len(results)}/{self.window} torréfactions chargées depuis {self.alog_dir}")
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
        self.tolerance_c = tolerance_c
        self.stability_std = stability_std
        self.polling_dt = polling_dt
        maxlen = max(5, int(window_sec / polling_dt))
        self._temps: deque = deque(maxlen=maxlen)
        self._times: deque = deque(maxlen=maxlen)
        self.seconds_stable: float = 0.0
        self._stable_since: Optional[float] = None

    def update(self, t_c: float, sv_c: float) -> None:
        """Ajouter une mesure (°C interne)."""
        now = time.perf_counter()
        self._temps.append(t_c)
        self._times.append(now)

        if self._check_stable(sv_c):
            if self._stable_since is None:
                self._stable_since = now
            self.seconds_stable = now - self._stable_since
        else:
            self._stable_since = None
            self.seconds_stable = 0.0

    def _check_stable(self, sv_c: float) -> bool:
        n = len(self._temps)
        if n < 5:
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

    ## TILAU ## ── Simulator isolation (INVARIANT) ──────────────────────────────
    A simulated preheat (``aw.simulator is not None``) MUST NOT persist or learn
    anything: it may run the control law and read learned params, but it never
    trains the real controller. This is enforced at every write path — keep all
    three guards if this code is refactored:
      • _on_preheat_complete()  → returns before _learn_law_params() (no learning)
      • _save_law_params()      → no per-SV P_ss/lead write
      • _migrate_persisted_law()→ no law_version stamp / no bucket purge
    load_law_params() only reads, so a simulated run gets the learned (or default)
    params and writes nothing back. Running a preheat in Simulator is therefore a
    safe dry-run: it cannot alter your real learned P_ss/lead buckets.
    """
    ## TILAU ## ── Cross-roast control-law learning (P_ss + lead_sec) ───────────
    ## Replaces the retired fuzzy-zone integrator. Only two knobs are learned, both
    ## consumed directly by compute_fuzzy_power via load_law_params():
    ##   P_ss     — steady hold power near SV (closes the proportional droop over roasts)
    ##   lead_sec — projection lead (raise → brake earlier when a roast overshot)
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
    _LAW_VERSION: int = 2              # bump ⇒ purge pre-redesign persisted state (relay-law buckets)
    ## TILAU ## ── Cold-start seeding from the historical alog corpus ────────────
    ## When a SV bucket has no learned value yet, seed P_ss and lead_sec from past
    ## roasts instead of a flat default. P_ss uses hold_mean_power but ONLY from
    ## post-calibration alogs (pre-Nov-2025 burner values are ~2× the real reading);
    ## lead uses the observed overshoot, which is a temperature and thus calibration-
    ## independent, so it may use the whole corpus.
    _SEED_SV_WINDOW_C: float = 15.0    # roasts within ±this of the target SV are relevant
    _SEED_MIN_ROASTS: int = 3          # need at least this many to trust a seed (else fall back)
    _SEED_LEAD_OVERSHOOT_GAIN: float = 0.4  # +s of lead per °C of mean historical overshoot beyond deadband
    # Burner-calibration cutoff: alogs older than 2025-11-01 have doubled fire values
    # (see corpus notes) and must NOT seed the absolute hold power P_ss.
    _SEED_CALIB_CUTOFF_EPOCH: float = 1761955200.0  # 2025-11-01 00:00 UTC

    def _adaptive_init(
        self,
        alog_dir: Optional[str] = None,
        window: int = 10,
        ambient: Optional[AmbientConditions] = None, 
        aw: ApplicationWindow | None = None , 
    ) -> None:
        """Initialise tous les sous-systèmes adaptatifs."""
        # Répertoire alog : fixé par l'application (clé QSettings 'alogDirectory',
        # même source que routine_check / roast_plan_model / beancave). On ne DEVINE
        # jamais — deviner risque de scanner le mauvais dossier.
        if alog_dir is None:
            alog_dir = self._configured_alog_dir()

        self.aw=aw

        self._alog_scanner = AlogScanner(alog_dir, window, aw=self.aw)
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
        self._session_hold_samples: List[float] = []   ## TILAU ## burner samples within ±_HOLD_BAND_C of SV → P_ss learning
        self._session_start_time: float = 0.0
        self._session_reached_sv: bool = False
        self._session_reach_time: float = 0.0
        self._session_max_bt: float = 0.0

        # Chargement initial de l'historique
        self._load_history()
        ## TILAU ## One-time migration: drop the pre-redesign relay-law persisted state.
        self._migrate_persisted_law()
        _logd.debug(
            f"AdaptivePIDMixin initialisé | alog_dir={alog_dir} "
            f"window={window} | {len(self._adaptive_memory._history)} torréfactions en mémoire"
        )

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

        # NOTE: the control law is now proportional-on-projected-temperature; the only
        # learned knobs it consumes are P_ss and lead_sec (see load_law_params /
        # _learn_law_params). Here we only keep the burner-ceiling adjustment, which
        # effective_max_burner() clamps DOWN against the hard cfg.max_burner cap.
        self._adj_max_burner = max(40.0, min(100.0,
            base_burner + lp.max_burner_adj))

        _logd.debug(
            f"Paramètres adaptatifs [conf={lp.confidence:.2f}, n={lp.n_samples}]: "
            f"burner={self._adj_max_burner:.1f}% (base={base_burner:.1f}%) | "
            f"ambient_factor={self._ambient_factor:.3f}"
        )

    # ── Méthodes à appeler depuis TilauPreheatPID ──────────────────────────
    ## TILAU ## ── Cross-roast control-law persistence (P_ss + lead_sec) ─────────

    def _law_param_keys(self) -> tuple[str, str]:
        """QSettings keys bucketed by SV (10°C buckets) so distinct targets keep
        independent hold/lead learning."""
        bucket = int(round(self.cfg.target_sv / 10.0) * 10)
        return f"tilaupid/p_ss_{bucket}", f"tilaupid/lead_{bucket}"

    def _migrate_persisted_law(self) -> None:
        """One-shot removal of pre-redesign persisted state (the relay-law
        zone-integrator buckets). Idempotent; gated by a stored law_version.
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
        removed = 0
        for key in list(s.allKeys()):
            if key.startswith("tilaupid/zone_integrator_"):
                s.remove(key)
                removed += 1
        s.setValue("tilaupid/law_version", int(self._LAW_VERSION))
        _logd.debug(f"TilauPID: migrated to law v{self._LAW_VERSION} "
                    f"({removed} stale integrator bucket(s) purged)")

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
        held = [m for m in near if m.hold_mean_power > 0]
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
        # Lead seeds from measured overshoot, which is only defined for recorded-SV holds.
        # Since extraction now admits only marked PID preheats, this gate simply requires
        # enough such roasts to exist; older manual preheats never enter the corpus, so lead
        # stays at the safe default until real PID preheats accumulate.
        if summ["n_held_recorded"] >= self._SEED_MIN_ROASTS and summ["mean_overshoot_c"] is not None:
            excess = max(0.0, summ["mean_overshoot_c"] - self._OVERSHOOT_DEADBAND_C)
            lead_seed = self.cfg.lead_sec_default + self._SEED_LEAD_OVERSHOOT_GAIN * excess

        return p_ss_seed, lead_seed

    def load_law_params(self) -> tuple[float, float]:
        """Return (P_ss, lead_sec) for the current SV bucket, clamped to safe ranges.

        Priority per knob: a persisted learned value (real roasts) → a corpus seed
        (historical alogs) → the physical/config default. The corpus seed means a
        fresh install does not start from zero, and — because reads never write and
        the simulator never persists — a simulated preheat runs fully corpus-informed
        while leaving real learned buckets untouched.
        """
        self._migrate_persisted_law()
        s = QSettings()
        k_pss, k_lead = self._law_param_keys()

        seed_p_ss, seed_lead = self._seed_law_params_from_history()

        ## TILAU ## Defaults when no seed: physical hold estimate for P_ss
        ## (_base_hold_power ≈ 18 + SV/9.5, ~39% at 200°C — a flat 20% would settle
        ## the drum below SV−1 and strand the learner in a cold droop), config for lead.
        default_p_ss = seed_p_ss if seed_p_ss is not None else \
            float(getattr(self, "_base_hold_power", self.cfg.p_ss_default))
        default_lead = seed_lead if seed_lead is not None else self.cfg.lead_sec_default

        try:
            p_ss = float(s.value(k_pss, default_p_ss, float))
        except (TypeError, ValueError):
            p_ss = default_p_ss
        try:
            lead = float(s.value(k_lead, default_lead, float))
        except (TypeError, ValueError):
            lead = default_lead
        p_ss = max(self._PSS_MIN, min(self.effective_max_burner(), p_ss))
        lead = max(self.cfg.lead_sec_min, min(self.cfg.lead_sec_max, lead))
        return p_ss, lead

    def format_law_diagnostic(self) -> str:
        """One-line human summary of the corpus + resolved params for the start-up log."""
        sv = self.cfg.target_sv
        summ = self.law_corpus_summary(sv)
        s = QSettings()
        k_pss, k_lead = self._law_param_keys()
        learned = "learned" if s.contains(k_pss) else "seed/default"
        pss_med = summ["p_ss_median"]
        mo = summ["mean_overshoot_c"]
        rr = summ["mean_ramp_ror"]
        return (
            f"PID corpus @SV={sv:.0f}°C [{learned}] | "
            f"roasts near={summ['n_near']} held={summ['n_held']} "
            f"calibrated={summ['n_held_calibrated']} | "
            f"hold_median={'n/a' if pss_med is None else f'{pss_med:.1f}%'} "
            f"overshoot_mean={'n/a' if mo is None else f'{mo:.1f}°C'} "
            f"ramp_mean={'n/a' if rr is None else f'{rr:.1f}°C/min'} "
            f"→ P_ss={self.p_ss:.1f}% lead={self.lead_sec:.1f}s"
        )

    def _save_law_params(self, p_ss: float, lead: float) -> None:
        """Persist learned params for the current SV bucket. Never writes under
        the simulator (a simulated preheat must not train the real controller)."""
        if getattr(getattr(self, "aw", None), "simulator", None) is not None:
            return
        s = QSettings()
        k_pss, k_lead = self._law_param_keys()
        s.setValue(k_pss, float(p_ss))
        s.setValue(k_lead, float(lead))

    def adaptive_start(self, ambient: Optional[AmbientConditions] = None) -> None:
        """
        À appeler depuis start() de TilauPreheatPID, APRÈS l'init de session.
        Recharge l'historique (prend en compte d'éventuelles nouvelles torréfactions)
        et met à jour les conditions ambiantes.
        """
        if ambient is not None:
            self._current_ambient = ambient
        self._session_rors.clear()
        self._session_burner_hold.clear()
        self._session_hold_samples.clear()
        self._session_start_time = time.perf_counter()
        self._session_reached_sv = False
        self._session_reach_time = 0.0
        self._session_max_bt: float = 0.0
        # Recharger l'historique à chaque start (fenêtre glissante réelle)
        self._load_history()
        # NOTE: learned P_ss/lead are (re)loaded by TilauPreheatPID.start() via
        # load_law_params(), which is bucketed on the current SV — nothing to do here.

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
        self._session_max_bt = max(getattr(self, '_session_max_bt', 0.0), t_c)

        # Accumulation des métriques de session
        if ror_c_per_min > 0:
            self._session_rors.append(ror_c_per_min)

        # Détection du premier passage à SV
        if not self._session_reached_sv and t_c >= sv_c - 1.0:
            self._session_reached_sv = True
            self._session_reach_time = time.perf_counter()
            _logd.debug(f"Session: SV atteinte ({t_c:.1f}°C)")

        # Accumulation puissance hold (après atteinte SV) — métrique legacy
        if self._session_reached_sv and burner > 0:
            self._session_burner_hold.append(float(burner))

        ## TILAU ## P_ss learning sample: burner commanded while genuinely AT SV
        ## (|t−SV| ≤ hold band). This is the steady power the drum actually needs
        ## to hold, so learning it here closes the proportional droop cross-roast.
        if self._session_reached_sv and abs(t_c - sv_c) <= self._HOLD_BAND_C and burner > 0:
            self._session_hold_samples.append(float(burner))

        # Stabilisation
        self._stabilisation_detector.update(t_c, sv_c)
        slope = self._stabilisation_detector.slope_c_per_min()
        quality = self._stabilisation_detector.ramp_quality()

        if self._stabilisation_detector.is_stable(min_duration_sec=15.0):
            _logd.debug(
                f"STABLE | T={t_c:.2f}°C SV={sv_c:.1f}°C "
                f"pente={slope:+.2f}°C/min {quality} "
                f"depuis {self._stabilisation_detector.seconds_stable:.0f}s"
            )
        else:
            _logd.debug(
                f"T={t_c:.2f}°C | pente={slope:+.2f}°C/min | {quality} | "
                f"stable={self._stabilisation_detector.seconds_stable:.0f}s"
            )

    def _learn_law_params(self) -> None:
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
        sv = self.cfg.target_sv
        max_bt = getattr(self, "_session_max_bt", 0.0)
        overshoot = max(0.0, max_bt - sv)
        reached = self._session_reached_sv
        approached = max_bt >= sv - self._APPROACH_MIN_C   # got within 10°C of SV at least
        t_settle = self._stabilisation_detector.mean_temp()
        slope = self._stabilisation_detector.slope_c_per_min()
        # A quasi-flat tail (|slope| small) NEAR SV is a settle point — whether it
        # settled ON SV or parked hot/cold. We must correct BOTH. The gate is slope +
        # proximity, NOT `reached`: a drum with P_ss too low settles a few °C BELOW SV
        # (never trips reached) yet still needs P_ss raised, and it is NOT is_stable
        # either (a ±1.5°C park fails that ±1°C test). The proximity band also rejects a
        # genuine mid-ramp plateau far from SV (which would nudge P_ss by 0.5·80→clamp).
        settled = (t_settle is not None
                   and abs(slope) <= 2.0
                   and abs(t_settle - sv) <= self._SETTLE_PROXIMITY_C)

        p_ss = float(getattr(self, "p_ss", self.cfg.p_ss_default))
        lead = float(getattr(self, "lead_sec", self.cfg.lead_sec_default))

        # ── lead_sec (projection lead ↔ transient overshoot) ──────────
        # Only learn from a roast that actually ran an approach: an early abort far
        # below SV must not ratchet the lead down on no real data.
        if overshoot > self._OVERSHOOT_DEADBAND_C:
            lead += self._LEAD_OVERSHOOT_GAIN * (overshoot - self._OVERSHOOT_DEADBAND_C)
        elif approached and not reached:
            lead -= self._LEAD_UNDERSHOOT_STEP
        lead = max(self.cfg.lead_sec_min, min(self.cfg.lead_sec_max, lead))

        # ── P_ss (steady hold ↔ proportional droop) ───────────────────
        if settled:
            if abs(t_settle - sv) <= self._SETTLE_BAND_C and self._session_hold_samples:
                # Held cleanly at SV → trust the measured steady power. Neutralise the
                # ambient factor: the law commands P_ss·ambient_factor, so learning from
                # the raw commanded burner would re-apply the factor a second time.
                af = self._ambient_factor if self._ambient_factor > 1e-6 else 1.0
                measured = mean(self._session_hold_samples) / af
                p_ss = (1.0 - self._PSS_EMA_ALPHA) * p_ss + self._PSS_EMA_ALPHA * measured
            else:
                # Parked off SV (droop): +err raises hold if cold, lowers it if hot.
                p_ss += self._PSS_DROOP_GAIN * (sv - t_settle)
        p_ss = max(self._PSS_MIN, min(self.effective_max_burner(), p_ss))

        self.p_ss, self.lead_sec = p_ss, lead
        self._save_law_params(p_ss, lead)
        _logd.debug(
            f"Law learn: overshoot={overshoot:.1f}°C reached={reached} "
            f"slope={slope:+.2f}°C/min t_settle={t_settle} → P_ss={p_ss:.1f}% lead={lead:.1f}s"
        )

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

        ## TILAU ## Learn the live control knobs first — this runs even when SV was
        ## never reached, so an undershooting roast still shortens the brake lead.
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
            overshoot_c=max(0.0, getattr(self, '_session_max_bt', 0.0) - self.cfg.target_sv),
            time_to_sv_sec=reach_sec,
            stabilise_time_sec=self._stabilisation_detector.seconds_stable,
            hold_mean_power=(
                mean(self._session_hold_samples) if self._session_hold_samples else 0.0
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
        ## TILAU ## cfg.max_burner is a HARD safety ceiling: the learned adjustment
        ## may only pull the burner DOWN, never above the configured cap (80%).
        ## Previously the learned value (clamped to 100) could exceed the base and
        ## drive a radiant FIR drum to 87%, tripping its thermal cutoff.
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
            "is_stable": self._stabilisation_detector.is_stable(),
            "stable_since": round(self._stabilisation_detector.seconds_stable, 1),
            "slope_c_per_min": round(self._stabilisation_detector.slope_c_per_min(), 2),
            "ramp_quality": self._stabilisation_detector.ramp_quality(),
        }
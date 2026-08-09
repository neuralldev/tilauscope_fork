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
# TiLau 2025-2026

"""
RoastAssistantPanel — fenêtre flottante d'assistance contextuelle par phase.

Architecture
============
RoastAssistantPanel (QWidget, floating)
├── SetupBar          — sélection grain / cible Agtron / bouton START·STOP
├── BeanHeaderCard    — rappel grain actif (nom, process, densité, altitude)
└── QStackedWidget
    ├── page 0 : _IdlePage          — avant lancement de l'assistant
    ├── page 1 : _DryingPage        — phase SÉCHAGE
    ├── page 2 : _MaillardPage      — phase MAILLARD
    ├── page 3 : _DevelopmentPage   — phase DÉVELOPPEMENT
    └── page 4 : _PreheatPage       — préchauffage (avant CHARGE)

Intégration dans TilauScope
===========================
1. Instancier dans TilauScope.init_ui() :
       self.roast_assistant = RoastAssistantPanel(self.aw, self)
       self.roast_assistant.hide()

2. Appeler à chaque cycle depuis update_ui_from_artisan() :
       if self.roast_assistant.isVisible() and self.roast_assistant.is_active:
           self.roast_assistant.on_artisan_update(data, value)

3. Synchroniser la phase depuis _handle_milestone_events() :
       self.roast_assistant.set_phase("DRY" | "MAI" | "DEV" | "COOL")

4. Notifier le début/fin du préchauffage depuis handle_preheat() :
       self.roast_assistant.set_preheating(True | False)

5. Ajouter un raccourci clavier (ex. Key_A) dans keyPressEvent() :
       elif key == Qt.Key.Key_A and no_modifier:
           self.roast_assistant.toggle_visibility()
"""

import re
import bisect
import logging
import math
import time
import uuid
from collections import deque
from typing import TYPE_CHECKING, Final
from dataclasses import dataclass

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QComboBox, QListView, QStyledItemDelegate,
    QScrollArea, QStackedWidget, QSizePolicy, QApplication,
    QGraphicsOpacityEffect,
)
from PyQt6.QtCore import Qt, QPoint, QTimer, pyqtSlot, pyqtSignal

from artisanlib.main import ApplicationWindow

from artisanlib.util import fromCtoFstrict, fromFtoCstrict, weight_units, convertWeight

from tilauscope.tilauscope_types import (GreenBean, AGTRON_SCALES, AgtronScale, THEME,
    get_agtron_color, get_roc_color, get_ror_color_by_phase, get_ror_ideal_band,
    format_batch_label, to_agtron)
from tilauscope.roasters import RoasterManager, RoasterContext
from tilauscope.roast_plan_model import TilauScopeRoastPlan, heat_soak_correction
from tilauscope.roast_plan_snapshot import build_prediction_snapshot
## TILAU ## moteur de trim pur (v1b) — calé hors-app sur le corpus de roasts
from tilauscope.autopilot_core import (AutoPilotCore, TrimParams,
                                       Phase as _APPhase, Lever as _APLever)


if TYPE_CHECKING:
    from tilauscope.roast_bridge import RoastDataBridge

_logd: Final[logging.Logger] = logging.getLogger("tilau")

# ── Palette locale (reprend THEME de tilauscope_types) ────────────────────────
_BG          = THEME["BG"]
_SURFACE     = THEME["SURFACE"]
_TEXT        = THEME["TEXT"]
_SUBTEXT     = THEME["SUBTEXT"]
_ACCENT      = THEME["ACCENT"]
_BORDER      = THEME["BORDER"]
_OK          = THEME["SUCCESS"]   # vert
_WARN        = THEME["WARNING"]   # orange
_CRIT        = THEME["CRITICAL"]  # rouge
_FONT        = "font-family: 'JetBrains Mono';"

# ── Status codes renvoyés par les helpers ─────────────────────────────────────
_S_OK   = "ok"
_S_WARN = "warn"
_S_CRIT = "crit"

_STATUS_COLOR = {_S_OK: _OK, _S_WARN: _WARN, _S_CRIT: _CRIT}

# Plages Agtron affichées dans le ComboBox (nom humain → objet AgtronScale)
_AGTRON_CHOICES: list[AgtronScale] = [a for a in AGTRON_SCALES
                                       if a.name not in ("Extremely Dark",)]

# get_agtron_color / get_roc_color imported from tilauscope.tilauscope_types
        
# ══════════════════════════════════════════════════════════════════════════════
# Helpers de calcul — fonctions pures, sans dépendance Qt
# ══════════════════════════════════════════════════════════════════════════════

def _extract_uuid_from_beans_field(beans_text: str) -> str|None:
    """
    Extrait l'UUID stocké dans le champ 'beans' d'Artisan.
    Format attendu quelque part dans la chaîne : 'uuid:<valeur>'
    """
    if not beans_text:
        return None
    m = re.search(r"uuid: ([a-f0-9\-]{32,36})", beans_text, re.IGNORECASE)
    return m.group(1) if m else None


def _eta_minutes(current_bt: float, target_bt: float, ror: float) -> float|None:
    """Temps estimé (minutes) pour atteindre target_bt au RoR courant."""
    if ror is None or ror <= 0.5:
        return None
    delta = target_bt - current_bt
    if delta <= 0:
        return 0.0
    return delta / ror


def _eta_minutes_decel(current_bt: float, target_bt: float,
                       ror_now: float, ror_end: float,
                       scale: float = 1.0) -> float|None:
    """
    ETA (minutes) en supposant un RoR déclinant linéairement de ror_now vers
    ror_end (le RoR de drop du plan) — modèle trapézoïdal.

    Le modèle à RoR constant (_eta_minutes) est systématiquement optimiste en
    développement : le RoR décélère, donc le temps réel est plus long que
    ΔT / RoR_courant. Repli sur le modèle constant si ror_end n'est pas
    exploitable (absent, nul, ou ≥ RoR courant).

    scale : 1.8 en °F — les gardes 0.5/0.3 sont en doctrine °C/min et les
    entrées (BT, RoR) sont en unité native.
    """
    if ror_now is None or ror_now <= 0.5 * scale:
        return None
    delta = target_bt - current_bt
    if delta <= 0:
        return 0.0
    if ror_end is None or ror_end <= 0.0 or ror_end >= ror_now:
        return delta / ror_now
    return delta / max(0.3 * scale, (ror_now + ror_end) / 2.0)


def _interp_sorted(x: float, xs: list, ys: list, lo: int = 0) -> "float | None":
    """Linear interpolation of ys at x over ascending xs (1-s grid). Clamps at
    ends. `lo` restricts the search to xs[lo:] WITHOUT slicing (no copy) —
    used by the hot-path plan-curve lookup to skip the non-monotonic pre-TP
    segment."""
    n = len(xs)
    if n == 0 or n != len(ys) or lo >= n:
        return None
    if x <= xs[lo]:
        return float(ys[lo])
    if x >= xs[-1]:
        return float(ys[-1])
    hi = n - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if xs[mid] <= x:
            lo = mid
        else:
            hi = mid
    x0, x1 = xs[lo], xs[hi]
    if x1 == x0:
        return float(ys[lo])
    f = (x - x0) / (x1 - x0)
    return float(ys[lo]) + f * (float(ys[hi]) - float(ys[lo]))


def _plan_curve_ref(plan: dict | None, bt_now: float, t_now_sec: float
                    ) -> "tuple[float | None, float | None]":
    """
    Position du roast sur la courbe BT planifiée (bt_plan_curve).

    Retourne (delta_sec, ror_ref) :
      delta_sec — avance (+) / retard (−) sur le plan, en secondes : écart
                  entre l'instant où le plan prévoyait d'atteindre bt_now
                  et l'instant courant.
      ror_ref   — pente planifiée (°/min, unité native) À CETTE POSITION de
                  la courbe. C'est la référence RoR correcte : comparer au
                  RoR moyen de phase fait lire « above plan » à tort en début
                  de Maillard, où la courbe planifiée est elle-même au-dessus
                  de sa moyenne.

    (None, None) quand la courbe est absente ou que bt_now est dans la zone
    du dip post-charge (courbe non monotone avant le TP → interpolation
    inverse ambiguë).
    """
    try:
        pc = plan.get("bt_plan_curve") if plan else None
        if not pc:
            return None, None
        t_grid   = pc.get("time_min") or []
        bt_grid  = pc.get("bt_plan")  or []
        ror_grid = pc.get("ror_plan") or []
        tp = _waypoint(pc.get("waypoints") or [], "tp", 1)
        if tp is None or len(t_grid) < 2 or len(t_grid) != len(bt_grid):
            return None, None
        tp_time = float(tp["time_min"])
        tp_bt   = float(tp["bt"])
        if bt_now <= tp_bt + 2.0:
            return None, None
        # Post-TP segment: BT rises monotonically by construction (PCHIP on
        # ascending anchors), so the inverse lookup bt → time is well defined.
        # bisect + lo-bounded interpolation: no per-tick list copies (hot path).
        i0 = bisect.bisect_left(t_grid, tp_time)
        if len(t_grid) - i0 < 2:
            return None, None
        t_ref_min = _interp_sorted(bt_now, bt_grid, t_grid, lo=i0)
        if t_ref_min is None:
            return None, None
        delta_sec = t_ref_min * 60.0 - t_now_sec
        ror_ref = (_interp_sorted(t_ref_min, t_grid, ror_grid)
                   if len(ror_grid) == len(t_grid) else None)
        return delta_sec, ror_ref
    except (TypeError, ValueError, KeyError, IndexError):
        return None, None


def _fmt_plan_delta(delta_sec: float) -> str:
    """+90 → '+1:30' ; −24 → '−0:24' (avance/retard sur le plan)."""
    sign = "+" if delta_sec >= 0 else "−"
    m, s = divmod(int(round(abs(delta_sec))), 60)
    return f"{sign}{m}:{s:02d}"


def _waypoint(wps: list, key: str, fallback_idx: int) -> "dict | None":
    """
    Résout un waypoint de courbe plan par sa CLÉ stable ("charge", "tp",
    "dry_end", "fc_start", "pre_drop", "drop") — les labels sont traduits et
    les positions peuvent bouger si un waypoint est inséré. fallback_idx
    couvre les plans générés avant l'ajout du champ "key".
    """
    for wp in wps:
        if wp.get("key") == key:
            return wp
    return wps[fallback_idx] if 0 <= fallback_idx < len(wps) else None


def _plan_ror_at_waypoint(plan: dict | None, key: str, fallback_idx: int) -> float | None:
    """RoR planifié (°/min, unité native) au waypoint `key` de la courbe plan.
    Sert de pente terminale au modèle d'ETA décéléré."""
    try:
        pc = plan.get("bt_plan_curve") if plan else None
        if not pc:
            return None
        wp = _waypoint(pc.get("waypoints") or [], key, fallback_idx)
        t_grid = pc.get("time_min") or []
        ror_grid = pc.get("ror_plan") or []
        if wp is None or len(t_grid) != len(ror_grid) or len(t_grid) < 2:
            return None
        return _interp_sorted(float(wp["time_min"]), t_grid, ror_grid)
    except (TypeError, ValueError, KeyError, IndexError):
        return None


def _next_ramp_step(plan: dict | None, bt_now: float) -> "tuple[float, int] | None":
    """Prochain step de la rampe heater anticipée (plan['Heater Ramp']) encore
    devant nous : première entrée dont le seuil BT est au-dessus de la BT
    courante. None si pas de rampe ou tous les steps déjà déclenchés."""
    try:
        for step in (plan or {}).get("Heater Ramp") or []:
            if float(step["bt"]) > bt_now:
                return float(step["bt"]), int(step["heater"])
    except (TypeError, ValueError, KeyError):
        pass
    return None


def _dev_crash_threshold(ror_target_drop: float, mode: str,
                         fallback: float = 3.0) -> float:
    """
    Seuil de crash RoR en développement, dérivé du plan.

    Un dark roast finit NORMALEMENT à 1,0–1,5 °C/min (c'est le drop_ror que
    le plan lui-même cible) : un plancher fixe à 3,0 lisait cette fin nominale
    comme un crash et bipait en continu. Seuil = 0,6 × RoR de drop planifié,
    avec un plancher absolu de 0,8 °C/min (un plan bruité à ~0 ne doit jamais
    désactiver l'alerte). Sans plan : ancien seuil fixe. Le RoR du plan est
    déjà en unité native ; seuls les constantes internes sont scalées en °F.
    """
    scale = 1.8 if mode == 'F' else 1.0
    if ror_target_drop and ror_target_drop > 0:
        return max(0.8 * scale, 0.6 * ror_target_drop)
    return fallback * scale


def _dtr_realtime(t_now_sec: float, t_charge_sec: float, t_fcs_sec: float) -> float|None:
    """DTR temps réel en % : (temps depuis FC) / (temps depuis CHARGE) × 100."""
    total = t_now_sec - t_charge_sec
    dev   = t_now_sec - t_fcs_sec
    if total <= 0 or dev < 0:
        return None
    return (dev / total) * 100.0


def _ror_smoothed(ror: float, ror_hist) -> float:
    """
    Médiane des 5 derniers RoR — l'entrée de lissage COMMUNE des ETA décélérés
    (pages Maillard et Développement) : la valeur instantanée est trop bruitée
    pour un compte à rebours stable. Repli sur la valeur instantanée quand
    l'historique est trop court.
    """
    if ror_hist is not None and len(ror_hist) >= 3:
        recent = sorted(list(ror_hist)[-5:])
        return recent[len(recent) // 2]
    return ror


def _ror_trend(delta2_history: "list[float] | deque[float]") -> str:
    """
    Analyse les 5 dernières valeurs de RoR pour déterminer la tendance.
    Retourne '↑' / '→' / '↓'.
    """
    if len(delta2_history) < 3:
        return "→"
    recent = list(delta2_history)[-5:]
    slope = recent[-1] - recent[0]
    if slope > 0.5:
        return "↑"
    if slope < -0.5:
        return "↓"
    return "→"


def _plan_ror(plan: dict | None, key: str, default: float = 0.0) -> float:
    """
    Extrait une valeur RoR du plan en float.
    Les valeurs du plan sont stockées comme strings (f"{val:.1f}").
    Retourne `default` si la clé est absente ou non convertible.
    """
    if plan is None:
        return default
    try:
        return float(plan.get(key, default))
    except (TypeError, ValueError):
        return default


def _parse_plan_duration(plan: dict | None, key: str) -> float | None:
    """
    Extrait une durée du plan dict (format 'mm:ss' stocké par format_time())
    et la retourne en secondes.
    Retourne None si la clé est absente, vide ou non parseable.
    """
    if plan is None:
        return None
    val = plan.get(key)
    if not val:
        return None
    try:
        ts = str(val).strip()
        if ":" in ts:
            minutes, seconds = map(int, ts.split(':'))
            return float(minutes * 60 + seconds)
        # Fallback numérique — supposé en minutes (même convention que format_time)
        return float(ts) * 60.0
    except (ValueError, TypeError):
        return None


def _dtr_projected(
    t_now_sec:  float,
    t_fcs_sec:  float,
    eta_min:    float | None,
) -> float | None:
    """
    DTR projeté à la température de drop, à partir d'un ETA fourni — l'appelant
    (page DEV) passe l'ETA du modèle DÉCÉLÉRÉ (_eta_minutes_decel), donc la
    projection intègre bien le déclin du RoR en développement.

    Paramètres
    ----------
    t_now_sec : temps écoulé depuis CHARGE (s) — t_charge_sec = 0 par convention Artisan
    t_fcs_sec : temps du FC START depuis CHARGE (s)
    eta_min   : ETA drop en minutes, issu de _eta_minutes() (None si RoR trop faible)

    Retourne le DTR% projeté au DROP, ou None si non calculable.
    """
    if eta_min is None or eta_min < 0 or t_fcs_sec <= 0:
        return None
    eta_sec         = eta_min * 60.0
    t_dev_at_drop   = (t_now_sec - t_fcs_sec) + eta_sec
    t_total_at_drop = t_now_sec + eta_sec
    if t_total_at_drop <= 0 or t_dev_at_drop < 0:
        return None
    return (t_dev_at_drop / t_total_at_drop) * 100.0


_HEATER_COL_BY_PHASE: Final = {"drying": 0, "maillard": 1, "development": 2}


def _apply_slider_value(aw, idx: int, value: float) -> bool:
    """Pose une valeur ABSOLUE sur un slider Artisan en un geste — même chemin
    que _QuickAdjustButton (setValue + handle_ui_input_released déclenche
    l'événement Artisan et l'action machine). Borne au range du slider et
    arrondit au pas de résolution de l'événement. Retourne True si appliqué.

    C'est la brique des actions one-tap : appliquer un step de rampe heater
    au brûleur sans que l'opérateur ait à cliquer N fois sur ± du quick-adjust."""
    try:
        sld = aw.tilauscope_main.sld_list[idx]
        if sld is None:
            return False
        try:
            step = int(aw.eventSliderStepSize(idx)) or 1
        except Exception:  # pylint: disable=broad-except
            step = 1
        target = int(round(value / step) * step)
        target = max(sld.minimum(), min(sld.maximum(), target))
        sld.setValue(target)
        aw.tilauscope_main.handle_ui_input_released(idx)
        return True
    except (AttributeError, IndexError, TypeError) as e:
        _logd.warning(f"apply slider {idx}={value} failed: {e}")
        return False


def _plan_heater_pct(plan: "dict | None", phase: str) -> "float | None":
    """Heater % planifié pour la phase, depuis 'Heater (%) (Dry|Mai|Dev)'
    ('70% | 60% | 40%'). None si absent / non parsable."""
    try:
        col = _HEATER_COL_BY_PHASE.get(phase)
        if col is None or not plan:
            return None
        parts = str(plan.get("Heater (%) (Dry|Mai|Dev)", "")).split(" | ")
        return float(parts[col].strip().rstrip("%"))
    except (ValueError, IndexError, TypeError):
        return None


## TILAU ## AutoPilot v1a — hard burner ceiling. SOURCE UNIQUE = TrimParams.max_burner_pct
## (le trim et le feedforward/rampe partagent le même plafond ; changer de torréfacteur
## ne se règle qu'à un seul endroit). Partagé en esprit avec le PID de préchauffe.
_AP_MAX_BURNER: Final = TrimParams().max_burner_pct

## TILAU ## Fenêtre de grâce (s) après le CHARGE : le handoff PID préchauffe→roast
## bouge transitoirement les sliders (à l'instant du dump, la BT plonge et le PID de
## préchauffe pousse le feu avant d'être coupé). Pendant cette fenêtre, AUTO SUIT les
## sliders sans se mettre en pause — sinon il se désarmait tout seul à la charge auto.
_AP_CHARGE_SETTLE_S: Final = 8.0
## TILAU ## KILL-SWITCH AutoPilot (décision Tilau 2026-07-11) : le mode AUTO est
## retiré de l'accès utilisateur — la puce n'apparaît pas et l'armement est
## refusé. Le sujet repart de zéro sur le banc (doctrine settings-first : les
## réglages sont la cause, le RoR la conséquence — cf. mémoire
## feedback_settings_first_doctrine). Repasser à True UNIQUEMENT après
## validation banc + GO explicite de Tilau.
_AP_USER_ENABLED: Final = False
## TILAU ## Dev en AUTO — « tenir le feu » (spec AutoPilot §3quater/§3quinquies) :
## la coupe rapide du feu en dev = LA cause des crashes post-FC (rate-limiter
## ÷2,5 le risque) ; le filet réactif est minimal, AIR d'abord, offset borné
## auto-résorbé. Flag A/B : feedforward-seul+filet vs feedforward+trim (v1b).
_AP_DEV_RATE_PCT_PER_MIN: Final = 5.0   # descente feu max en fenêtre exotherme
_AP_DEV_RATE_WINDOW_S: Final = 75.0     # fenêtre exotherme FC → FC+75 s
_AP_NET_STEP_PCT: Final = 2.0           # touche du filet (2 %/4-5 s, jamais bloc 5 %)
_AP_NET_CADENCE_S: Final = 5.0          # cadence des touches du filet
_AP_NET_CAP_PCT: Final = 6.0            # borne d'offset AIR du filet (3 touches)
_AP_NET_RESORB_QUIET_S: Final = 25.0    # calme requis avant résorption de l'offset
_AP_FF_ONLY_KEY: Final = "tilauscope/ap_feedforward_only"  # flag A/B (QSettings caché)

## TILAU ## plan keys of the per-phase lever values, by Artisan slider index
_AP_LEVER_KEYS: Final = {
    0: "Airflow (%) (Dry|Mai|Dev)",
    1: "Drum Speed (%) (Dry|Mai|Dev)",
    2: "Extraction (%) (Dry|Mai|Dev)",
}
_AP_PHASE_COL: Final = {"DRY": 0, "MAI": 1, "DEV": 2}
_AP_PHASE_WORD: Final = {"DRY": "drying", "MAI": "maillard", "DEV": "development"}

## TILAU ## Réglages de refroidissement posés par l'AutoPilot au DROP : couper le
## brûleur, ventiler et extraire fort, tambour rapide (les grains sont sortis —
## le verrou drum_midroast_locked ne s'applique plus). Valeurs Tilau/Skywalker,
## à migrer en RoasterContext si une autre machine en veut d'autres.
_AP_COOLING_LEVERS: Final = {3: 0.0, 0: 75.0, 2: 75.0, 1: 80.0}  # burner, air, ext, drum


def _ap_curve_ror_c(plan: dict | None, t_min: float, mode: str) -> "float | None":
    """## TILAU ## RoR PLANIFIÉE RÉELLE (°C/min) au temps t_min, interpolée depuis
    `bt_plan_curve.ror_plan` — la courbe physiquement modélisée (décélérante),
    pas une moyenne scalaire. C'est LA cible correcte pour l'écart affiché et le
    trim : comparer le RoR réel à la RoR prévue AU MÊME POINT. °F → ÷1.8."""
    try:
        c = (plan or {})["bt_plan_curve"]
        tm, rp = c["time_min"], c["ror_plan"]
        if not tm or len(tm) != len(rp):
            return None
        if t_min <= tm[0]:
            v = rp[0]
        elif t_min >= tm[-1]:
            v = rp[-1]
        else:
            i = bisect.bisect_left(tm, t_min)
            i = min(max(i, 1), len(tm) - 1)
            t0, t1 = tm[i - 1], tm[i]
            f = 0.0 if t1 == t0 else (t_min - t0) / (t1 - t0)
            v = rp[i - 1] + (rp[i] - rp[i - 1]) * f
        return (v / 1.8) if mode == 'F' else float(v)
    except (KeyError, TypeError, ValueError, IndexError):
        return None


def _ap_phase_endpoints(plan: dict | None, phase_key: str,
                        mode: str) -> "tuple[float, float]":
    """## TILAU ## Cibles RoR (début, fin) de phase pour l'AutoPilotCore, en °C/min,
    ÉCHANTILLONNÉES SUR LA VRAIE COURBE du plan aux temps des jalons (fix
    2026-07-10 : l'ancienne reconstruction géométrique produisait une cible
    Maillard plate qui ne suivait pas la courbe → écarts % incohérents). Repli
    sur les moyennes scalaires seulement si la courbe manque."""
    try:
        wps = (plan or {})["bt_plan_curve"]["waypoints"]
        k0, k1 = ("dry_end", "fc_start") if phase_key == "MAI" else ("fc_start", "drop")
        w0, w1 = _waypoint(wps, k0, -1), _waypoint(wps, k1, -1)
        r0 = _ap_curve_ror_c(plan, float(w0["time_min"]), mode)
        r1 = _ap_curve_ror_c(plan, float(w1["time_min"]), mode)
        if r0 is not None and r1 is not None:
            return max(0.5, r0), max(0.5, r1)
    except (KeyError, TypeError, ValueError, IndexError):
        pass
    # repli géométrique (pas de courbe)
    s = 1.8 if mode == 'F' else 1.0
    avg_mai = _plan_ror(plan, "Target ROR Maillard") / s
    avg_dev = _plan_ror(plan, "Target ROR Dev (Avg)") / s
    if phase_key == "MAI":
        end = max(0.5, avg_dev)
        return max(end, 2.0 * avg_mai - end), end
    start = max(0.5, avg_dev * 1.3)
    return start, max(0.5, 2.0 * avg_dev - start)


def _ap_phase_span_sec(plan: dict | None, phase_key: str) -> "float | None":
    """## TILAU ## Durée planifiée (s) de la phase MAI/DEV depuis les waypoints
    de la courbe du plan vivant (clés stables). None si indisponible."""
    try:
        wps = (plan or {})["bt_plan_curve"]["waypoints"]
        k0, k1 = ("dry_end", "fc_start") if phase_key == "MAI" else ("fc_start", "drop")
        w0, w1 = _waypoint(wps, k0, -1), _waypoint(wps, k1, -1)
        span = (float(w1["time_min"]) - float(w0["time_min"])) * 60.0
        return span if span > 30.0 else None
    except (KeyError, TypeError, ValueError, IndexError):
        return None


def _ap_ramp_crossed(plan: dict | None, bt_prev: float,
                     bt_now: float) -> "tuple[float, int] | None":
    """## TILAU ## Palier de rampe heater FRANCHI ce tick : entrée de
    plan['Heater Ramp'] dont le seuil BT vient d'être traversé EN MONTANT
    (bt_prev < seuil <= bt_now). Un franchissement montant uniquement — au
    CHARGE la sonde lit la température du tambour puis PLONGE vers le TP en
    traversant tous les seuils vers le bas : cette descente ne doit jamais
    déclencher un palier (bug observé : palier pre-FC 51 % appliqué au début
    du séchage). None si aucun seuil franchi ce tick."""
    if bt_now <= bt_prev:
        return None
    hit: "tuple[float, int] | None" = None
    try:
        for step in (plan or {}).get("Heater Ramp") or []:
            thr = float(step["bt"])
            if bt_prev < thr <= bt_now:
                hit = (thr, int(step["heater"]))   # dernier seuil du tick
    except (TypeError, ValueError, KeyError):
        return None
    return hit


def _ap_entry_ramp_crossed(plan: dict | None, key: str, bt_prev: float,
                           bt: float) -> "dict | None":
    """## TILAU ## Étage de la rampe `key` (plan[key], liste d'entrées {bt, ...})
    FRANCHI ce tick, en MONTANT (bt_prev < seuil <= bt). Renvoie le dernier
    (plus haut) étage franchi — valeurs absolues auto-réparatrices : un saut de
    BT qui sauterait un étage atterrit sur la bonne consigne suivante. None si
    aucun seuil franchi. Sert la « Dev Ramp » (feu/air/ext en dev) et l'« Air
    Ramp » (montée airflow de Maillard)."""
    if bt <= bt_prev:
        return None
    hit: "dict | None" = None
    try:
        for step in (plan or {}).get(key) or []:
            thr = float(step["bt"])
            if bt_prev < thr <= bt:
                hit = step
    except (TypeError, ValueError, KeyError):
        return None
    return hit


def _burner_slider_idx(aw) -> int:
    """Index du slider burner — même résolution que la page preheat
    (config du PID de préchauffe, repli historique 3 — intentionnel)."""
    try:
        tpid = getattr(aw, "tilauPreheatingPid", None)
        return (getattr(tpid, "cfg", None) and tpid.cfg.heater_slider) or 3
    except AttributeError:
        return 3


def _ror_deviation_advice(
    ror: float,
    target: float,
    mode: str,
    phase: str,
    above_is_crit: bool = True,  # kept for signature compat
    aw=None,
    plan: "dict | None" = None,
) -> tuple[str, str]:
    """
    RoR status, PLAN-FIRST (design validé 2026-07-04) :

    - Cible plan disponible (target > 0) : le NIVEAU se calcule sur l'écart
      relatif à la cible (ok < 15 %, warn < 30 %, crit au-delà ; plancher
      absolu 0,5 °C/min sous lequel on ne dévie jamais du ok). Les bandes
      génériques de phase ne servent plus que de repli sans plan — un roast
      sur un plan dont la pente locale sort de la bande générique ne lit
      plus « drifting » à tort.
    - Quantification « un cran » (item E, étude 3) : quand le burner vif
      s'écarte du heater planifié DANS le sens du défaut (≥ 1 pas), le conseil
      suggère UN cran de ~5 % vers le plan (borné à la valeur planifiée) en
      citant le plan (« burner 75% → un cran vers 70% (plan 60%) ») — jamais
      un bloc de 15 % d'un coup (qui provoque le pompage).
    - Conscience de l'inertie : après un mouvement du burner (opérateur OU
      alarme de rampe — aw._tilau_burner_watch, posé par le panneau), le
      conseil directionnel est suspendu pendant le lag machine et remplacé
      par « ⏳ effet d'ici ~N s », SAUF si l'écart continue de se creuser.
      Les alertes crash (hors de cette fonction) ne sont jamais débouncées.

    RoR != RoC: this classifies the RoR (bean temperature, deg/min). The
    Agtron/min Rate-of-Colour is handled by get_roc_color().
    """
    del above_is_crit
    unit  = f"°{mode}/min"
    scale = 1.8 if mode == 'F' else 1.0

    adiff: "float | None" = None
    if target > 0:
        # Seuils ADAPTATIFS : le plan les calibre selon la confiance de son
        # historique (grid ×1.35 → tolérant sur grain neuf ; learned serré
        # ×0.8 → exigeant sur grain maîtrisé). Repli sur 15/30 % sans plan.
        rel_ok, rel_warn = 0.15, 0.30
        try:
            _tols = (plan or {}).get("Plan Tolerances") or {}
            rel_ok   = float(_tols.get("ror_rel_ok",   rel_ok))
            rel_warn = float(_tols.get("ror_rel_warn", rel_warn))
        except (TypeError, ValueError, AttributeError):
            pass
        diff  = ror - target
        adiff = abs(diff)
        rel   = adiff / target
        if adiff < 0.5 * scale or rel < rel_ok:
            level, direction = "ok", "normal"
        elif rel < rel_warn:
            level, direction = "warn", ("high" if diff > 0 else "low")
        else:
            level, direction = "crit", ("high" if diff > 0 else "low")
    else:
        level, direction, _color = get_ror_color_by_phase(ror, phase, mode)
    status = {"ok": _S_OK, "warn": _S_WARN, "crit": _S_CRIT}.get(level, _S_OK)

    if direction == "normal":
        if target > 0:
            return _S_OK, QApplication.translate(
                "tilauscope_roast_assistant", "On plan (target {0} {1})").format(f"{target:.1f}", unit)
        lo, hi = get_ror_ideal_band(phase, mode)
        return status, QApplication.translate(
            "tilauscope_roast_assistant", "On plan (ideal {0}–{1} {2})").format(f"{lo:.0f}", f"{hi:.0f}", unit)

    # ── Fenêtre d'inertie : un mouvement burner vient d'avoir lieu ─────────
    watch = getattr(aw, "_tilau_burner_watch", None) if aw is not None else None
    if watch:
        try:
            elapsed = time.monotonic() - float(watch["t"])
            lag = float(watch.get("lag", 30.0))
            # Écart de référence posé au 1er passage après le mouvement.
            if watch.get("dev0") is None and adiff is not None:
                watch["dev0"] = adiff
            worsening = (adiff is not None and watch.get("dev0") is not None
                         and adiff > float(watch["dev0"]) + max(0.3 * scale, 0.10 * target))
            if 0.0 <= elapsed < lag and not worsening:
                remain = max(1, int(round(lag - elapsed)))
                return _S_OK, QApplication.translate(
                    "tilauscope_roast_assistant",
                    "⏳ burner {0}→{1}% — effect in ~{2} s").format(
                    f"{watch.get('from', '?')}", f"{watch.get('to', '?')}", remain)
        except (KeyError, TypeError, ValueError):
            pass

    arrow = (QApplication.translate("tilauscope_roast_assistant", "↑ above") if direction == "high"
             else QApplication.translate("tilauscope_roast_assistant", "↓ below"))
    if target > 0:
        ref = f"{ror:.1f} vs {target:.1f} {unit}"
    else:
        lo, hi = get_ror_ideal_band(phase, mode)
        ref = f"{lo:.0f}–{hi:.0f} {unit}"

    # ── Quantification plan « UN CRAN » (item E, étude 3) ─────────────────
    # La correction validée par la pratique = UN cran de ~5 %, jamais un bloc
    # (« burner 75% vs plan 60% » se lisait « fais −15 % d'un coup » = pompage).
    # On suggère le prochain pas vers le plan, borné à la valeur planifiée, en
    # citant le plan pour la transparence. Un cran = 5 % (granularité mesurée),
    # jamais plus fin que la résolution du slider.
    action: "str | None" = None
    plan_heater = _plan_heater_pct(plan, phase)
    burner = _read_slider_pct(aw, _burner_slider_idx(aw)) if aw is not None else None
    if plan_heater is not None and burner is not None:
        res = 1.0
        try:
            _rctx = getattr(aw, "_tilau_roast_context", None)
            res = float(getattr(_rctx, "heater_resolution_pct", 1.0) or 1.0)
        except (TypeError, ValueError):
            res = 1.0
        gap = burner - plan_heater
        _cran = max(res, 5.0)   # granularité corrective mesurée (étude 3)
        # Ne citer le plan que s'il pointe dans le sens du conseil — sinon le
        # burner est déjà au niveau planifié et la comparaison embrouillerait.
        if direction == "high" and gap >= res:
            _next = round(max(plan_heater, burner - _cran) / res) * res
            action = QApplication.translate(
                "tilauscope_roast_assistant", "burner {0}% → one notch to {1}% (plan {2}%)").format(
                f"{burner:.0f}", f"{_next:.0f}", f"{plan_heater:.0f}")
        elif direction == "low" and gap <= -res:
            _next = round(min(plan_heater, burner + _cran) / res) * res
            action = QApplication.translate(
                "tilauscope_roast_assistant", "burner {0}% → one notch to {1}% (plan {2}%)").format(
                f"{burner:.0f}", f"{_next:.0f}", f"{plan_heater:.0f}")
    if action is None:
        action = (QApplication.translate("tilauscope_roast_assistant", "one notch down on the burner") if direction == "high"
                  else QApplication.translate("tilauscope_roast_assistant", "one notch up on the burner"))
    prefix = "⚠ " if status == _S_CRIT else ""
    return status, QApplication.translate(
        "tilauscope_roast_assistant", "{0}{1} plan ({2}) — {3}").format(prefix, arrow, ref, action)


def _read_slider_pct(aw, idx: int):
    """Current value (%) of an Artisan event slider, or None if unavailable.
    Index map (this rig): 0=Airflow (integrated rear ventilation), 1=Drum,
    2=Damper (= AirWave extraction), 3=Burner."""
    try:
        sld = aw.tilauscope_main.sld_list[idx]
        return int(sld.value()) if sld is not None else None
    except (AttributeError, IndexError, TypeError):
        return None


# AirWave / external extractor cooling threshold, OBSERVED on the Skywalker rig:
# <=30% has no measurable effect on BT; above it the extraction starts to cool the
# drum interior. Specific to this extractor+roaster combo, NOT a generic constant.
_AIRWAVE_COOLING_PCT: Final = 30


_AIRWAVE_MODE_BY_PHASE = {"drying": "FAN", "maillard": "STD", "development": "EXT"}


# Fenêtre d'approche d'un jalon (minutes) : plancher de repli quand le graphe ne
# publie pas de proximité (coach off, ETA non calculable). Le signal PRINCIPAL
# est _coach_approaching() ci-dessous, lu DIRECTEMENT depuis l'état publié par le
# graphe — même prédiction que le message « approaching », donc bouton et alerte
# s'allument ensemble. Unité de temps → pas de scaling °F.
_APPROACH_MIN: Final = 1.5


def _milestone_suggestion(aw, which: str, max_age_s: float = 30.0) -> "dict | None":
    """Suggestion de jalon fraîche publiée par le détecteur (#10) : lit
    qmc._tilau_milestone_suggest, filtre sur le jalon `which` ("DE"|"FC") et
    l'âge (le détecteur cesse de publier une fois le jalon marqué → la
    suggestion expire seule). None sinon."""
    try:
        s = getattr(aw.qmc, "_tilau_milestone_suggest", None)
        if not s or s.get("which") != which:
            return None
        if time.monotonic() - float(s.get("t_mono", 0.0)) > max_age_s:
            return None
        return s
    except (AttributeError, TypeError, ValueError):
        return None


def _coach_approaching(aw, toward: str) -> bool:
    """True quand le coach du graphe signale l'approche du jalon `toward`
    ("DE" | "FC"). Lit l'état publié par tgraphcanvas._coach_html à chaque
    redraw (qmc._tilau_coach_pub) — le bouton du panneau s'allume ainsi
    EXACTEMENT en même temps que l'alerte « approaching » du graphe, qui
    utilise le moteur prédictif d'Artisan (et non l'ETA décéléré du panneau,
    qui divergeait). None/other → False, le plancher température prend le relais."""
    try:
        pub = getattr(aw.qmc, "_tilau_coach_pub", None)
        return bool(pub) and pub.get("toward") == toward and bool(pub.get("approaching"))
    except AttributeError:
        return False


def _airflow_status(aw, pct, phase: str):
    """Integrated ventilation (airflow slider 0) status -> (value, sub, status).
    The integrated fan is the true drum-airflow / browning lever, distinct from
    the AirWave extraction. Directional advice is pull-aware via inlet_air_mode
    (cached on aw by the panel)."""
    if pct is None:
        return "--", "", _S_OK
    pull = getattr(aw, "_tilau_inlet_air_mode", "push") == "pull"
    if phase == "drying":
        sub = (QApplication.translate("tilauscope_roast_assistant", "Integrated airflow — keep low to conserve heat") if pull
               else QApplication.translate("tilauscope_roast_assistant", "Integrated airflow — moderate for even drying"))
    elif phase == "maillard":
        sub = QApplication.translate("tilauscope_roast_assistant", "Integrated airflow — raise to manage browning & chaff")
    else:
        sub = QApplication.translate("tilauscope_roast_assistant", "Integrated airflow")
    return f"{pct}%", sub, _S_OK


def _extraction_status(aw, pct, phase: str = ""):
    """AirWave / extraction (damper slider 2) status -> (value, sub, status).
    Smoke device, NOT a browning lever; above ~30% it cools the drum on this rig.
    When an AirWave device is present, also PROPOSES the per-phase mode
    (FAN/STD/EXT) -- a suggestion only; the actual switch is done by alarms or
    (later) a one-tap command. Inlet temp pulled from the BLE device if present."""
    if pct is None:
        return "--", "", _S_OK
    if pct > _AIRWAVE_COOLING_PCT:
        status = _S_WARN
        sub = QApplication.translate(
            "tilauscope_roast_assistant", "Above ~{0}% — cooling the drum").format(_AIRWAVE_COOLING_PCT)
    else:
        status = _S_OK
        sub = QApplication.translate("tilauscope_roast_assistant", "Smoke extraction — neutral on BT")
    val = f"{pct}%"
    airwave = getattr(aw, "bleAirwaveDevice", None)
    if airwave is not None:
        try:
            val = f"{float(airwave.state.last_inlet):.0f}° / {pct}%"
        except (AttributeError, TypeError):
            pass
        rec = _AIRWAVE_MODE_BY_PHASE.get(phase)
        if rec:
            sub = f"{sub} · " + QApplication.translate(
                "tilauscope_roast_assistant", "recommend MODE {0}").format(rec)
    return val, sub, status


def _send_airwave_command(aw, cmd: str) -> bool:
    """Send a Difluid AirWave command string ("MODE FAN"|"MODE STD"|"MODE EXT",
    "FAN 30", ...) iff the device is defined and online (same guard as canvas.py).
    Returns True if dispatched. Parsed by Difluid.send_command()."""
    try:
        if getattr(aw, "bleAirwaveDeviceName", None) is not None and getattr(aw, "bleAirwaveDevice", None) is not None:
            aw.bleAirwaveDevice.send_command(cmd)
            return True
    except Exception as e:
        _logd.warning(f"AirWave command '{cmd}' failed: {e}")
    return False


def _send_airwave_mode(aw, mode_cmd: str) -> bool:
    """Send an AirWave MODE command, then re-assert the current fan speed (slider 2)
    in the SAME call. Changing mode makes the device restore its last known fan
    value (e.g. 50%), spiking useless turbulence; re-sending the live value prevents it."""
    fan = _read_slider_pct(aw, 2)
    cmd = mode_cmd if fan is None else f"{mode_cmd}, FAN {fan}"
    return _send_airwave_command(aw, cmd)


def _seconds_since_event(aw, idx: int):
    """Seconds elapsed since an Artisan timeindex event (0=CHARGE, 1=DRY END,
    2=FC START), or None if it hasn't occurred yet / no samples."""
    try:
        qmc = aw.qmc
        ti = qmc.timeindex[idx]
        if ti is None or ti < 0 or not qmc.timex:
            return None
        return float(qmc.timex[-1] - qmc.timex[ti])
    except (AttributeError, IndexError, TypeError):
        return None


class _RoRCrashDetector:
    """
    Détecte un crash RoR imminent à partir de la pente sur la fenêtre glissante.

    Logique
    -------
    - Calcule la pente (°/min²) sur les N dernières valeurs de ror_hist
    - Si pente < SLOPE_THRESHOLD et distance à la température cible < _temp_proximity
      pendant au moins CONSECUTIVE_TICKS cycles consécutifs → crash imminent
    - Émet un beep Qt et retourne un message d'alerte

    Réinitialisation automatique si la pente se redresse.

    Note mode
    ---------
    reset(mode) doit être appelé à chaque changement de phase pour adapter
    _temp_proximity à l'unité courante (°C ou °F).
    """
    SLOPE_THRESHOLD    = -0.8   # deg/min PER SECOND - dangerous fall rate (dt-normalised)
    _TEMP_PROXIMITY_C  = 12.0   # deg C - vigilance window before the target temperature
    MIN_DURATION_SEC   = 6.0    # seconds the condition must hold (sample-rate invariant)
    ROR_FLOOR          = 5.0    # deg/min - RoR genuinely low (not mere deceleration)
    ## TILAU ## Calibration DEV (banc corpus 2026-07-11, spec §3quinquies) : la
    ## pente −0,8/s attrapait 0/21 crashes de dev (chute réelle ~−0,24/s). Le
    ## crash franc = perte de RoR sur une fenêtre GLISSANTE de 15 s ; seuil 3,0
    ## °C/min = conservateur (66 % catch / ~10 % fausses alertes, filet minimal).
    DEV_FALL_WINDOW_S    = 15.0  # fenêtre de mesure de la chute (dev)
    DEV_FALL_C_PER_WIN   = 3.0   # °C/min perdus sur la fenêtre → crash franc
    DEV_MIN_SPAN_S       = 10.0  # historique mini couvert avant de juger
    DEV_MIN_DURATION_SEC = 5.0   # tenue de la condition (< 4-5 s = bruit)
    DRUM_QUIET_S         = 30.0  # muet après un geste tambour (artefact de MESURE RoR)

    def __init__(self) -> None:
        self._consecutive:    int   = 0
        self._last_beep_ror:  float = 0.0
        self._temp_proximity: float = self._TEMP_PROXIMITY_C  # °C par défaut
        self._slope_threshold: float = self.SLOPE_THRESHOLD   # °C/min/s par défaut
        self._ror_floor:       float = self.ROR_FLOOR         # °C/min par défaut
        self._dev_fall_thr:    float = self.DEV_FALL_C_PER_WIN  # °C/min/15 s par défaut
        self._drum_quiet_until: float = 0.0   # monotonic — survit au reset()

    def notify_drum_event(self) -> None:
        """## TILAU ## Un mouvement du tambour pollue la MESURE du RoR (excursion
        +50 % médiane, 64/81 roasts du corpus) : toute détection RoR est muette
        pendant DRUM_QUIET_S. Volontairement NON remis à zéro par reset()."""
        self._drum_quiet_until = time.monotonic() + self.DRUM_QUIET_S

    def reset(self, mode: str = 'C') -> None:
        """
        Réinitialise le détecteur et adapte tous les seuils à l'unité.
        Doit être appelé à chaque set_phase().
        """
        self._consecutive   = 0
        self._last_beep_ror = 0.0
        # Spans / RoR / pentes : ce sont tous des DELTAS → scaling ×1.8 en °F
        _s = 9.0 / 5.0 if mode == 'F' else 1.0
        self._temp_proximity  = self._TEMP_PROXIMITY_C * _s
        self._slope_threshold = self.SLOPE_THRESHOLD * _s
        self._ror_floor       = self.ROR_FLOOR * _s
        self._dev_fall_thr    = self.DEV_FALL_C_PER_WIN * _s

    def check(
        self,
        ror: float,
        ror_hist: "deque[float]",
        bt: float,
        target_temp: float,
        dt: float = 1.0,
        dev_mode: bool = False,
    ) -> str | None:
        """
        Retourne un message d'alerte si crash imminent, None sinon.

        dt-aware : la pente est normalisee par le temps reel ((n-1)*dt) et la duree
        de confirmation est en SECONDES (MIN_DURATION_SEC), pas en nombre de ticks,
        donc independante du reglage d'echantillonnage Artisan (qmc.delay).

        dev_mode : critère DEV recalibré (chute cumulée sur fenêtre 15 s, sans
        garde de proximité cible — un crash de dev arrive n'importe où entre FC
        et drop). Le conseil est AIR d'abord : on ne re-coupe JAMAIS le feu.
        """
        if len(ror_hist) < 4:
            return None
        if time.monotonic() < self._drum_quiet_until:
            self._consecutive = 0   ## TILAU ## fenêtre tambour : mesure RoR polluée
            return None

        dt = dt if (dt and dt > 0) else 1.0
        if dev_mode:
            _n = min(len(ror_hist), max(2, int(round(self.DEV_FALL_WINDOW_S / dt)) + 1))
            _vals = list(ror_hist)[-_n:]
            _span = (len(_vals) - 1) * dt
            if _span < self.DEV_MIN_SPAN_S:
                return None
            # chute normalisée à la fenêtre nominale (°C/min perdus / 15 s)
            _fall = (_vals[0] - _vals[-1]) * (self.DEV_FALL_WINDOW_S / _span)
            if _fall >= self._dev_fall_thr:
                self._consecutive += 1
                _req = max(2, int(-(-self.DEV_MIN_DURATION_SEC // dt)))
                if self._consecutive >= _req:
                    if abs(ror - self._last_beep_ror) > 0.5:
                        QApplication.beep()
                        self._last_beep_ror = ror
                    return QApplication.translate(
                        "tilauscope_roast_assistant",
                        "⚠ RoR crash — {0}°/min lost in 15s — support with AIR, never cut the fire"
                    ).format(f"{_fall:.1f}")
            else:
                self._consecutive = 0
            return None
        vals  = list(ror_hist)[-4:]
        span_sec = max(1e-6, (len(vals) - 1) * dt)
        slope = (vals[-1] - vals[0]) / span_sec            # deg/min per second

        gap_to_target = target_temp - bt
        required_ticks = max(2, int(-(-self.MIN_DURATION_SEC // dt)))   # ceil(MIN_DURATION_SEC/dt)

        if (slope < self._slope_threshold
                and ror < self._ror_floor
                and 0 < gap_to_target < self._temp_proximity):
            self._consecutive += 1
            if self._consecutive >= required_ticks:
                if abs(ror - self._last_beep_ror) > 0.5:
                    QApplication.beep()
                    self._last_beep_ror = ror
                return QApplication.translate(
                    "tilauscope_roast_assistant",
                    "⚠ RoR crash — {0}°/min/s slope, {1}° from target — raise heater now"
                ).format(f"{slope:.1f}", f"{gap_to_target:.1f}")
        else:
            self._consecutive = 0

        return None

def _fmt_sec(sec: float) -> str:
    """Formate des secondes en 'mm:ss' lisible (ex. 255 → '4:15')."""
    m, s = divmod(int(sec), 60)
    return f"{m}:{s:02d}"


# ══════════════════════════════════════════════════════════════════════════════
# Widgets de base réutilisables
# ══════════════════════════════════════════════════════════════════════════════

class _SectionTitle(QLabel):
    """Titre de section petit, en gris clair uppercase."""
    def __init__(self, text: str):
        super().__init__(text.upper())
        self.setStyleSheet(
            f"color: #585B70; font-size: 9px; font-weight: 800; {_FONT} border: none;"
        )

class _MetricCard(QFrame):
    """
    Carte affichant une métrique :
        ┌────────────────────────────────┐
        │ LABEL                       ↑  │
        │  123.4 °C/min                ● │
        │  sous-titre contextuel         │
        └────────────────────────────────┘

    status = 'ok' | 'warn' | 'crit'
    """
    def __init__(self, label: str, unit: str = "", color: str = _ACCENT):
        super().__init__()
        self._color = color
        self._unit  = unit

        self.setStyleSheet(f"""
            QFrame {{
                background: {_SURFACE};
                border: 1px solid {_BORDER};
                border-radius: 10px;
            }}
            QLabel {{ border: none; background: transparent; }}
        """)
        self.setMinimumHeight(60)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(3)

        # Ligne 1 : label + indicateur de statut
        top = QHBoxLayout()
        top.setSpacing(4)
        self._lbl_title = QLabel(label.upper())
        self._lbl_title.setStyleSheet(
            f"color: #585B70; font-size: 10px; font-weight: 800; "
            f"{_FONT} letter-spacing: 0.8px;"
        )
        self._lbl_status = QLabel("●")
        self._lbl_status.setStyleSheet(
            f"color: {_BORDER}; font-size: 11px; {_FONT}"
        )
        top.addWidget(self._lbl_title)
        top.addStretch()
        top.addWidget(self._lbl_status)

        # Ligne 2 : valeur principale — grande et lisible
        self._lbl_value = QLabel("--")
        self._lbl_value.setStyleSheet(
            f"color: {color}; font-size: 26px; font-weight: 900; {_FONT}"
        )

        # Ligne 3 : contexte / sous-titre — contraste augmenté
        self._lbl_sub = QLabel("")
        self._lbl_sub.setStyleSheet(
            f"color: #94A3B8; font-size: 10px; {_FONT}"
        )
        self._lbl_sub.setWordWrap(True)

        layout.addLayout(top)
        layout.addWidget(self._lbl_value)
        layout.addWidget(self._lbl_sub)

    def update(self, value: str, sub: str = "", status: str = _S_OK,
               trend: str = "") -> None:
        display = f"{value} {self._unit}".strip()
        if trend:
            display += f"  {trend}"
        if self._lbl_value.text() != display:
            self._lbl_value.setText(display)
        if self._lbl_sub.text() != sub:
            self._lbl_sub.setText(sub)
        dot_color = _STATUS_COLOR.get(status, _BORDER)
        if status != _S_OK:
            self._lbl_value.setStyleSheet(f"color: {dot_color}; font-size: 20px;")
        else:
            self._lbl_value.setStyleSheet(f"color: {self._color}; font-size: 22px;")

    def set_color(self, color: str) -> None:
        self._color = color
        self._lbl_value.setStyleSheet(
            f"color: {color}; font-size: 22px; font-weight: bold; {_FONT} border: none;"
        )

class _AlertBanner(QLabel):
    """
    Bandeau d'alerte contextuelle affiché sous les cartes.
    Caché quand vide.
    """
    def __init__(self):
        super().__init__("")
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMaximumHeight(48)
        self._set_style(_S_OK)
        self.hide()

    def _set_style(self, level: str) -> None:
        color = _STATUS_COLOR.get(level, _BORDER)
        # Fond semi-transparent basé sur la couleur du niveau
        bg_map = {
            _S_OK:   "rgba(166,227,161,0.08)",
            _S_WARN: "rgba(249,226,175,0.08)",
            _S_CRIT: "rgba(243,139,168,0.08)",
        }
        bg = bg_map.get(level, f"{_SURFACE}")
        self.setStyleSheet(f"""
            QLabel {{
                background: {bg};
                border: 1px solid {color}88;
                border-radius: 7px;
                color: {color};
                font-size: 11px;
                font-weight: 700;
                {_FONT}
                padding: 6px 10px;
            }}
        """)

    def show_alert(self, text: str, level: str = _S_WARN) -> None:
        self._set_style(level)
        self.setText(text)
        self.setVisible(bool(text))

    def clear(self) -> None:
        self.setText("")
        self.hide()

# ══════════════════════════════════════════════════════════════════════════════
# Widgets groupe B2 — Présentation « héro » (layout B, low-density)            ## TILAU ##
#   _HeroMetric : une seule métrique dominante par page (grand chiffre).
#   _MiniChip / _ChipRow : contexte compact secondaire.
#   _CoachLine : ligne de conseil unique, teintée par niveau (remplace la
#                multiplication des sous-titres + bannières disséminés).
# ══════════════════════════════════════════════════════════════════════════════

class _HeroMetric(QWidget):
    """Single dominant metric: small label, large value (+unit/trend), sub-line.

    The big value is rich-text so the unit and trend arrow render smaller than
    the number while inheriting the JetBrains Mono family from the base sheet.
    All setters guard against no-op updates to stay cheap on the 1 Hz path.
    """
    _VAL_MIN_H: Final[int] = 60      # 46 px glyphs + ascender/descender room

    def __init__(self, label: str, unit: str = "", color: str = _ACCENT):
        super().__init__()
        self._unit  = unit
        self._color = color
        self._last_html = None
        self._last_sub  = None
        self._last_lbl  = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(3)
        lay.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self._lbl = QLabel(label.upper())
        self._lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl.setStyleSheet(
            f"color: #6C7086; font-size: 10px; font-weight: 800; "
            f"{_FONT} letter-spacing: 1.5px; border: none;"
        )
        self._val = QLabel("--")
        self._val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._val.setTextFormat(Qt.TextFormat.RichText)
        self._val.setStyleSheet(f"{_FONT} border: none;")
        # A rich-text QLabel reports a tiny minimum height (its content may
        # wrap), so a squeezed page shrank it below the 46 px glyphs and the
        # number was sliced top and bottom. Reserve the line height.  ## TILAU ##
        self._val.setMinimumHeight(self._VAL_MIN_H)
        self._val.setSizePolicy(QSizePolicy.Policy.Preferred,
                                QSizePolicy.Policy.MinimumExpanding)
        self._sub = QLabel("")
        self._sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Wrap allowed: an unwrapped QLabel imposes its FULL text width as the
        # page's minimum width — through the QStackedWidget (max of all pages)
        # it made the anchored body wider than the scroll viewport (hscroll is
        # off), clipping every page's right edge. The sub-line is the longest
        # variable text of a page; two lines beat silent truncation.  ## TILAU ##
        self._sub.setWordWrap(True)
        self._sub.setTextFormat(Qt.TextFormat.RichText)   # tinted colour segment ## TILAU ##
        self._sub.setStyleSheet(f"color: #94A3B8; font-size: 11px; {_FONT} border: none;")
        self._sub.hide()

        lay.addWidget(self._lbl)
        lay.addWidget(self._val)
        lay.addWidget(self._sub)

    def set_label(self, text: str, color: str = "#6C7086") -> None:
        t = text.upper()
        if t != self._last_lbl:
            self._lbl.setText(t)
            self._lbl.setStyleSheet(
                f"color: {color}; font-size: 10px; font-weight: 800; "
                f"{_FONT} letter-spacing: 1.5px; border: none;"
            )
            self._last_lbl = t

    def update(self, value: str, sub: str = "",
               color: str | None = None, trend: str = "") -> None:
        c = color or self._color
        unit_html = (f" <span style='font-size:18px;color:#6C7086;font-weight:700'>"
                     f"{self._unit}</span>") if self._unit else ""
        trend_html = (f" <span style='font-size:26px;color:{c}'>{trend}</span>"
                      if trend else "")
        html = (f"<span style='font-size:46px;font-weight:800;color:{c}'>{value}</span>"
                f"{unit_html}{trend_html}")
        if html != self._last_html:
            self._val.setText(html)
            self._last_html = html
        if sub != self._last_sub:
            self._sub.setText(sub)
            self._sub.setVisible(bool(sub))
            self._last_sub = sub
            self._sync_sub_height()

    def _sync_sub_height(self) -> None:
        """Reserve the height the wrapped sub-line actually needs.  ## TILAU ##

        A word-wrapped QLabel reports the height of ONE line as its minimum, so
        a 3-line sub-line (heat-soak note on a narrow anchored panel) had its
        last line cut off. Called on text change and on resize only — never on
        the 1 Hz refresh when the text is unchanged.
        """
        w = self._sub.width()
        if w <= 0 or not self._sub.isVisible():
            return
        h = self._sub.heightForWidth(w)
        if h > 0 and self._sub.minimumHeight() != h:
            self._sub.setMinimumHeight(h)

    def resizeEvent(self, event) -> None:  # noqa: ANN001
        super().resizeEvent(event)
        self._sync_sub_height()


class _MiniChip(QFrame):
    """Compact context tile: tiny label over a value. Reused, never recreated."""
    def __init__(self):
        super().__init__()
        self.setStyleSheet(
            f"QFrame {{ background: {_SURFACE}; border: 1px solid {_BORDER}; "
            f"border-radius: 8px; }} QLabel {{ border: none; background: transparent; }}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 5, 8, 5)
        lay.setSpacing(1)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._l = QLabel("")
        self._l.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._l.setStyleSheet(
            f"color: #6C7086; font-size: 9px; font-weight: 800; "
            f"{_FONT} letter-spacing: 0.5px;"
        )
        self._v = QLabel("--")
        self._v.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._color = None
        self._set_value_style("#CDD6F4")
        lay.addWidget(self._l)
        lay.addWidget(self._v)

    def _set_value_style(self, color: str) -> None:
        self._v.setStyleSheet(
            f"color: {color}; font-size: 14px; font-weight: 800; {_FONT}"
        )
        self._color = color

    def set(self, label: str, value: str, color: str) -> None:
        if self._l.text() != label:
            self._l.setText(label)
        if self._v.text() != value:
            self._v.setText(value)
        if color != self._color:
            self._set_value_style(color)


class _ChipRow(QWidget):
    """Fixed pool of mini chips; unused slots are hidden, not destroyed."""
    def __init__(self, n: int = 5):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(7)
        self._chips = [_MiniChip() for _ in range(n)]
        for c in self._chips:
            lay.addWidget(c)

    def set_chips(self, items: "list[tuple[str, str, str]]") -> None:
        for i, chip in enumerate(self._chips):
            if i < len(items):
                lbl, val, col = items[i]
                chip.set(lbl, val, col)
                chip.show()
            else:
                chip.hide()


class _CoachLine(QLabel):
    """Single advice line. Neutral when steady; tinted on warn/crit. Replaces
    the scattered per-card subtitles and the separate alert banner."""
    def __init__(self):
        super().__init__("")
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._level = None
        self._apply(_S_OK)

    def _apply(self, level: str) -> None:
        if level == _S_OK:
            border, col = _BORDER, "#BAC2DE"
        else:
            c = _STATUS_COLOR.get(level, _BORDER)
            border, col = f"{c}88", c
        self.setStyleSheet(
            f"QLabel {{ background: {_SURFACE}; border: 1px solid {border}; "
            f"border-radius: 9px; color: {col}; font-size: 11.5px; "
            f"font-weight: 600; {_FONT} padding: 9px 11px; }}"
        )

    def set(self, text: str, level: str = _S_OK) -> None:
        if level != self._level:
            self._apply(level)
            self._level = level
        if self.text() != text:
            self.setText(text)

# ══════════════════════════════════════════════════════════════════════════════
# Widgets groupe C — Quick Adjust et boutons contextuels
# ══════════════════════════════════════════════════════════════════════════════

def _slider_cfg(aw: "ApplicationWindow", idx: int) -> tuple[str, int, str]:
    """
    Retourne (label, idx, color) pour un _QuickAdjustButton,
    en lisant les métadonnées Artisan : etypes[idx] et EvalueColor[idx].
    Lecture statique à l'init — pas de refresh en cours de session.
    """
    try:
        label = aw.qmc.etypes[idx].upper()
    except (AttributeError, IndexError):
        label = f"SLD{idx}"
    try:
        color = aw.qmc.EvalueColor[idx]
    except (AttributeError, IndexError):
        color = "#CDD6F4"
    return (label, idx, color)


def _filter_slider_configs(aw: "ApplicationWindow",
                           ctx: "RoasterContext | None",
                           configs: list[tuple[str, int, str]]
                           ) -> list[tuple[str, int, str]]:
    """Keep only the slider buttons whose underlying control is available.
    Preserves each page's own (label, idx, color) tuples — only filters them.
    idx convention: 0=Air(airflow) 1=Drum 2=Damper(AirWave) 3=Burner(heater).
    When ctx is None (roaster unknown) machine controls are kept; the AirWave
    damper (idx 2) is gated purely on the BLE device being present."""
    airwave_present = getattr(aw, "bleAirwaveDevice", None) is not None

    def _keep(idx: int) -> bool:
        if idx == 3:   # Burner / heater
            return ctx is None or ctx.has_heater_control
        if idx == 0:   # Air / airflow
            return ctx is None or ctx.has_airflow_control
        if idx == 1:   # Drum
            return ctx is None or ctx.drum_variable_speed
        if idx == 2:   # Damper / AirWave — hardware gated
            return airwave_present
        return True

    return [cfg for cfg in configs if _keep(cfg[1])]


def _roaster_is_readonly(aw: "ApplicationWindow") -> bool:
    """True quand l'opérateur a coché « lecture seule » pour le torréfacteur
    (case dans devices.py → aw.tilau_roaster_readonly) : la machine est pilotée
    à la main et Artisan ne lui envoie aucune commande. Les sliders et boutons
    de réglage n'ont alors aucun sens : l'assistant les masque et affiche des
    RECOMMANDATIONS de réglage à la place. Choix EXPLICITE et non plus déduit des
    capacités (trop ambigu : un Cormorant bricolé peut être pilotable, ou on peut
    ne vouloir qu'un écran de monitoring). L'AirWave (extracteur BLE séparé)
    n'entre pas dans ce calcul — il garde son bouton même en lecture seule."""
    return bool(getattr(aw, "tilau_roaster_readonly", False))


_RECO_KEYS: Final = (
    ("Heater (%) (Dry|Mai|Dev)",     "Burner"),
    ("Airflow (%) (Dry|Mai|Dev)",    "Air"),
    ("Drum Speed (%) (Dry|Mai|Dev)", "Drum"),
)


def _phase_reco_text(plan: "dict | None", phase_idx: int) -> str:
    """Recommandations de réglage lisibles pour la phase (0=dry,1=mai,2=dev),
    depuis les cibles du plan : « Burner 60% · Air 30% · Drum 75% ». Colonnes
    vides / non applicables ('--', 'N/A') ignorées. '' si pas de plan."""
    if not plan:
        return ""
    parts: list[str] = []
    for key, label in _RECO_KEYS:
        vals = str(plan.get(key, "")).split(" | ")
        if len(vals) > phase_idx:
            v = vals[phase_idx].strip()
            if v and v not in ("--", "N/A", "N/A%"):
                parts.append(f"{label} {v}")
    return "  ·  ".join(parts)


class _RecoRow(QLabel):
    """Bandeau de recommandations (lecture seule) — remplace la rangée de
    sliders sur un torréfacteur qui n'expose pas ses commandes."""
    def __init__(self) -> None:
        super().__init__("")
        self.setWordWrap(True)
        self.setStyleSheet(
            f"QLabel {{ background: {_SURFACE}; border: 1px dashed {_BORDER}; "
            f"border-radius: 8px; color: #A6ADC8; font-size: 11px; {_FONT} "
            f"padding: 8px 10px; }}")
        self._tr_prefix = QApplication.translate(
            "tilauscope_roast_assistant", "Recommended settings")
        self.hide()

    def set_reco(self, reco_text: str) -> None:
        txt = f"{self._tr_prefix} — {reco_text}" if reco_text else self._tr_prefix
        if self.text() != txt:
            self.setText(txt)


class _QuickAdjustButton(QFrame):
    """
    Bouton compact affichant le nom du slider + valeur courante.
    Au survol : la valeur se dimme et deux demi-zones ↑ / ↓ apparaissent.
    Clic haut → +step, Clic bas → −step, via le slider Artisan correspondant.

    slider_idx : index dans aw.sld_list (0=slider1, 1=slider2, ...)
    color      : couleur hex de la valeur (identitaire du slider)
    """
    def __init__(
        self,
        aw: "ApplicationWindow",
        label: str,
        slider_idx: int,
        color: str = "#CDD6F4",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.aw         = aw
        self._idx       = slider_idx
        self._color     = color

        self.setFixedSize(90, 56)
        self.setStyleSheet(f"""
            QFrame {{
                background: {_SURFACE};
                border: 1px solid {_BORDER};
                border-radius: 8px;
            }}
        """)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        # ── Label (nom + valeur) ──────────────────────────────────────────────
        self._lbl_name = QLabel(label.upper(), self)
        self._lbl_name.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._lbl_name.setStyleSheet(
            f"color: #a6adc8; font-size: 9px; font-weight: 700; "
            f"{_FONT} letter-spacing: 0.6px; border: none; background: transparent;"
        )

        self._lbl_val = QLabel("--", self)
        self._lbl_val.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._lbl_val.setStyleSheet(
            f"color: {color}; font-size: 18px; font-weight: 700; "
            f"{_FONT} border: none; background: transparent;"
        )

        lbl_layout = QVBoxLayout()
        lbl_layout.setContentsMargins(0, 0, 0, 0)
        lbl_layout.setSpacing(1)
        lbl_layout.addStretch()
        lbl_layout.addWidget(self._lbl_name)
        lbl_layout.addWidget(self._lbl_val)
        lbl_layout.addStretch()

        self._lbl_widget = QWidget(self)
        self._lbl_widget.setLayout(lbl_layout)
        self._lbl_widget.setGeometry(0, 0, 90, 56)
        self._lbl_widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        # ── Overlay ↑ / ↓ (invisible par défaut) ────────────────────────────
        self._btn_up = QPushButton("", self)
        self._btn_up.setGeometry(0, 0, 90, 27)
        self._btn_up.setStyleSheet("""
            QPushButton {
                background: transparent; border: none; border-radius: 0;
                font-size: 14px; color: #CDD6F4;
            }
            QPushButton:hover { background: #45475A99; }
        """)
        self._btn_up.setText("▲")
        self._btn_up.hide()

        self._btn_dn = QPushButton("", self)
        self._btn_dn.setGeometry(0, 29, 90, 27)
        self._btn_dn.setStyleSheet("""
            QPushButton {
                background: transparent; border: none; border-radius: 0;
                font-size: 14px; color: #CDD6F4;
            }
            QPushButton:hover { background: #45475A99; }
        """)
        self._btn_dn.setText("▼")
        self._btn_dn.hide()

        # Séparateur central entre les deux demi-zones
        self._sep = QFrame(self)
        self._sep.setGeometry(8, 28, 74, 1)
        self._sep.setStyleSheet(f"background: {_BORDER}; border: none;")
        self._sep.hide()

        self._btn_up.clicked.connect(self._on_up)
        self._btn_dn.clicked.connect(self._on_dn)

    def _get_sld(self):
        """Retourne le slider Artisan correspondant, via tilauscope_main."""
        try:
            return self.aw.tilauscope_main.sld_list[self._idx]
        except (AttributeError, IndexError):
            return None

    def refresh_value(self) -> None:
        """Lit la valeur courante du slider et met à jour l'affichage."""
        sld = self._get_sld()
        if sld is not None:
            self._lbl_val.setText(f"{sld.value()}%")
        else:
            self._lbl_val.setText("--")

    def enterEvent(self, event) -> None:  # type: ignore[override]
        self._lbl_widget.setGraphicsEffect(self._dim_effect(0.45))
        self._btn_up.show()
        self._btn_dn.show()
        self._sep.show()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        self._lbl_widget.setGraphicsEffect(None)
        self._btn_up.hide()
        self._btn_dn.hide()
        self._sep.hide()
        super().leaveEvent(event)

    def _dim_effect(self, opacity: float) -> QGraphicsOpacityEffect:
        fx = QGraphicsOpacityEffect(self._lbl_widget)
        fx.setOpacity(opacity)
        return fx

    def _step(self) -> int:
        try:
            return int(self.aw.eventSliderStepSize(self._idx))
        except Exception:
            return 5

    def _on_up(self) -> None:
        sld = self._get_sld()
        if sld is None:
            return
        try:
            new_val = min(sld.maximum(), sld.value() + self._step())
            sld.setValue(new_val)
            self.aw.tilauscope_main.handle_ui_input_released(self._idx)
            self.refresh_value()
        except Exception as e:
            _logd.warning(f"QuickAdjust up failed: {e}")

    def _on_dn(self) -> None:
        sld = self._get_sld()
        if sld is None:
            return
        try:
            new_val = max(sld.minimum(), sld.value() - self._step())
            sld.setValue(new_val)
            self.aw.tilauscope_main.handle_ui_input_released(self._idx)
            self.refresh_value()
        except Exception as e:
            _logd.warning(f"QuickAdjust dn failed: {e}")


class _QuickAdjustRow(QWidget):
    """
    Rangée horizontale de _QuickAdjustButton.
    slider_configs : list de (label, slider_idx, color_hex)
    """
    def __init__(
        self,
        aw: "ApplicationWindow",
        slider_configs: list[tuple[str, int, str]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._buttons: list[_QuickAdjustButton] = []
        for label, idx, color in slider_configs:
            btn = _QuickAdjustButton(aw, label, idx, color)
            self._buttons.append(btn)
            layout.addWidget(btn)
        layout.addStretch()

    def refresh(self) -> None:
        for b in self._buttons:
            b.refresh_value()


class _ContextButton(QPushButton):
    """
    Bouton d'action contextuel slim — marque une étape de torréfaction.
    S'active/désactive dynamiquement selon les conditions de phase.

    style : 'ok' | 'warn' | 'cancel' | 'purple' | 'dim'
    """
    _STYLES = {
        'ok':     ("border:1.5px solid #A6E3A1; color:#A6E3A1; background:rgba(166,227,161,0.08);",
                   "border:1.5px solid #A6E3A1; color:#A6E3A1; background:rgba(166,227,161,0.18);"),
        'warn':   ("border:1.5px solid #F9E2AF; color:#F9E2AF; background:rgba(249,226,175,0.08);",
                   "border:1.5px solid #F9E2AF; color:#F9E2AF; background:rgba(249,226,175,0.18);"),
        'cancel': ("border:1.5px solid #F38BA8; color:#F38BA8; background:rgba(243,139,168,0.08);",
                   "border:1.5px solid #F38BA8; color:#F38BA8; background:rgba(243,139,168,0.18);"),
        'purple': ("border:1.5px solid #CBA6F7; color:#CBA6F7; background:rgba(203,166,247,0.08);",
                   "border:1.5px solid #CBA6F7; color:#CBA6F7; background:rgba(203,166,247,0.18);"),
        'dim':    (f"border:1.5px solid {_BORDER}; color:#585B70; background:transparent;",
                   f"border:1.5px solid {_BORDER}; color:#585B70; background:transparent;"),
    }

    def __init__(self, label: str, hint: str = "", style: str = 'ok',
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._style = style
        self.maintext = label
        text = label if not hint else f"{label}\n{hint}"
        self.setText(text)
        self._apply_style(style)
        self.setStyleSheet(self.styleSheet() + f"""
            QPushButton {{
                font-size: 11px; font-weight: 700; {_FONT}
                border-radius: 7px; padding: 7px 8px;
            }}
        """)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _apply_style(self, style: str) -> None:
        normal, hover = self._STYLES.get(style, self._STYLES['dim'])
        self.setStyleSheet(f"""
            QPushButton {{ {normal} font-size: 11px; font-weight: 700;
                {_FONT} border-radius: 7px; padding: 7px 8px; }}
            QPushButton:hover {{ {hover} }}
            QPushButton:disabled {{ border:1.5px solid {_BORDER};
                color:#45475A; background:transparent; }}
        """)

    def set_style(self, style: str) -> None:
        self._style = style
        self._apply_style(style)

    def set_active(self, active: bool, style: str | None = None) -> None:
        self.setEnabled(active)
        if style:
            self._apply_style(style if active else 'dim')
        elif not active:
            self._apply_style('dim')

class _IdlePage(QWidget):
    """Affichée avant que l'assistant soit lancé."""
    def __init__(self, aw:ApplicationWindow):
        super().__init__()
        self.aw = aw
        self.ao = AccessOmniflux(aw)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl = QLabel()
        self._lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl.setWordWrap(True)
        self._lbl.setStyleSheet(
            f"color: #585B70; font-size: 16px; {_FONT} border: none;"
        )
        layout.addWidget(self._lbl)
        self.set_operator_level("guided")

    def set_operator_level(self, level: str) -> None:  ## TILAU ##
        if level == "guided":
            self._lbl.setText(QApplication.translate("tilauscope_roast_assistant",
                "Select a green bean and a roasting target,\nthen press  ▶  in Artisan to start."))
        else:
            self._lbl.setText(QApplication.translate("tilauscope_roast_assistant",
                "Select a green bean and a color target\nthen, click on  ▶  to start the assistant."))

class _PreheatPage(QWidget):
    """Preheat (between START/monitoring and CHARGE), layout B.

    Single hero metric + context chips + one coach line + a state banner on top.
    Two data modes share the same widgets:
      • PID active   → hero = distance to SV, chips = BT/RoR/HTR/SV/ETA
      • No PID       → hero = actual BT, chips = ET/RoR/charge-target
    """

    _ROR_PREHEAT_LOW = 4.0

    def __init__(self, aw: ApplicationWindow):
        super().__init__()
        self.aw = aw
        self.ao = AccessOmniflux(aw)

        # Charge button latch: once BT entered the SV±2° window it stays armed
        # even on a slight PID overshoot. Reset only on a new assistant start.
        self._charge_btn_latched: bool = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)

        # State banner (top) — always visible, carries phase + status
        self.banner = _AlertBanner()
        self.banner.setMaximumHeight(40)

        # Hero metric — relabelled per mode in refresh()
        self.hero = _HeroMetric(
            QApplication.translate("tilauscope_roast_assistant", "Until SV"), "°", "#A6E3A1")

        # Progress bar BT → SV (manual fill)
        prog_row = QHBoxLayout()
        prog_row.setSpacing(8)
        self._prog_outer = QFrame()
        self._prog_outer.setFixedHeight(8)
        self._prog_outer.setStyleSheet(f"background: {_BORDER}; border-radius: 4px;")
        self._prog_inner = QFrame(self._prog_outer)
        self._prog_inner.setFixedHeight(8)
        self._prog_inner.setStyleSheet(f"background: {_ACCENT}; border-radius: 4px;")
        self._lbl_prog_val = QLabel("0 %")
        self._lbl_prog_val.setFixedWidth(40)
        self._lbl_prog_val.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._lbl_prog_val.setStyleSheet(
            f"color: {_ACCENT}; font-size: 12px; font-weight: bold; {_FONT} border: none;")
        prog_row.addWidget(self._prog_outer)
        prog_row.addWidget(self._lbl_prog_val)

        # Context chips
        self.chips = _ChipRow(5)

        # Single coach line
        self.coach = _CoachLine()

        # Quick adjust — burner only during preheat
        self.quick_adjust = _QuickAdjustRow(aw, _filter_slider_configs(
            aw, getattr(aw, "_tilau_roast_context", None), [
                (QApplication.translate("tilauscope_roast_assistant", "Burner"), 3, "#F38BA8"),
            ]))
        # Torréfacteur sans commandes : pas de slider burner à régler.
        if _roaster_is_readonly(aw):
            self.quick_adjust.setVisible(False)

        # Charge button (terminal action)
        self.btn_charge = _ContextButton(
            QApplication.translate("tilauscope_roast_assistant", "Charge"),
            QApplication.translate("tilauscope_roast_assistant", "BT stable ± 2° from SV"),
            style='dim',
        )
        self.btn_charge.clicked.connect(lambda: aw.qmc.markChargeSignal.emit(False))
        self.btn_charge.set_active(False)

        layout.addWidget(self.banner)
        layout.addWidget(self.hero)
        layout.addLayout(prog_row)
        layout.addWidget(self.chips)
        layout.addWidget(self.coach)
        layout.addWidget(self.quick_adjust)
        layout.addWidget(self.btn_charge)
        layout.addStretch(1)

        # ── Translation cache (hot-path: called every 1 Hz refresh) ──────────
        self._lbl_until_sv   = QApplication.translate("tilauscope_roast_assistant", "Until SV")
        self._lbl_actual_bt  = QApplication.translate("tilauscope_roast_assistant", "Actual BT")
        # banner / state
        self._tr_sv_reached       = QApplication.translate("tilauscope_roast_assistant", "✅ SV reached — stabilize then charge")
        self._tr_approaching_sv   = QApplication.translate("tilauscope_roast_assistant", "⚠ Approaching SV — monitor inertia")
        self._tr_heating_to_sv    = QApplication.translate("tilauscope_roast_assistant", "Preheating — heating to SV")
        self._tr_no_pid_state     = QApplication.translate("tilauscope_roast_assistant", "Preheating — no PID active")
        # coach (single line)
        self._tr_coach_ready      = QApplication.translate("tilauscope_roast_assistant", "Hold 30–60 s, then charge once RoR drops under 5 °/min.")
        self._tr_coach_approach   = QApplication.translate("tilauscope_roast_assistant", "Approaching SV — PID will cut heat; slight overshoot is normal.")
        self._tr_coach_weak       = QApplication.translate("tilauscope_roast_assistant", "RoR weak despite active PID — check heater response.")
        self._tr_coach_ramping    = QApplication.translate("tilauscope_roast_assistant", "PID ramping to SV — let it work, charge when BT is stable ± 2°.")
        self._tr_coach_raise      = QApplication.translate("tilauscope_roast_assistant", "Raise heater — temperature is rising too slowly.")
        self._tr_coach_reduce     = QApplication.translate("tilauscope_roast_assistant", "Reduce heater — temperature is rising too fast.")
        self._tr_coach_normal     = QApplication.translate("tilauscope_roast_assistant", "Heat rate normal — wait for ET to stabilize, then charge.")
        # chip labels
        self._cl_bt   = QApplication.translate("tilauscope_roast_assistant", "BT")
        self._cl_et   = QApplication.translate("tilauscope_roast_assistant", "ET")
        self._cl_ror  = QApplication.translate("tilauscope_roast_assistant", "ROR")
        self._cl_htr  = QApplication.translate("tilauscope_roast_assistant", "HTR")
        self._cl_sv   = QApplication.translate("tilauscope_roast_assistant", "SV")
        self._cl_eta  = QApplication.translate("tilauscope_roast_assistant", "ETA")
        self._cl_chrg = QApplication.translate("tilauscope_roast_assistant", "CHRG")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _set_progress(self, pct: float) -> None:
        """Update the manual progress bar (0–100)."""
        pct = max(0.0, min(100.0, pct))
        total_w = self._prog_outer.width()
        if total_w > 0:
            self._prog_inner.setFixedWidth(max(8, int(total_w * pct / 100.0)))
        self._lbl_prog_val.setText(f"{pct:.0f}%")

    @staticmethod
    def _eta_text(eta: "float | None") -> str:
        if eta is None:
            return "--"
        if eta <= 0.1:
            return "~0m"
        return f"~{eta:.0f}m"

    # ── Public API ──────────────────────────────────────────────────────────────

    def refresh(
        self,
        bt: float,
        et: float,
        ror: float | None,
        ror_hist: list[float],
        mode: str,
        pid_active: bool,
        sv: float,
        heater_pct: int,
        charge_temp: float,
        soak_note: "str | None" = None,
    ) -> None:
        """Refresh the preheat page (signature unchanged — driven by displayscope).
        soak_note : ligne heat-soak back-to-back (batch 2+), affichée sous le héros."""
        unit  = f"°{mode}"
        trend = _ror_trend(ror_hist)
        ror_chip = f"{ror:.1f}" if ror is not None else "--"
        # °F doctrine: deltas/RoR scale ×1.8, absolute temps convert via
        # fromCtoFstrict. °C path stays bit-identical (s=1, identity temps).
        s = 1.8 if mode == 'F' else 1.0
        _room = 20.0 if mode == 'C' else fromCtoFstrict(20.0)

        if pid_active:
            dist = sv - bt
            # Hero: distance to SV, colour by proximity (reaching SV is good → green)
            if dist <= 0:
                hero_color = _OK
            elif dist < 5 * s:
                hero_color = _WARN
            else:
                hero_color = _ACCENT
            self.hero.set_label(self._lbl_until_sv)
            self.hero.update(f"{dist:.1f}", soak_note or "", hero_color)

            # Progress: ambient → SV
            try:
                ambient = float(self.aw.qmc.ambientTemp or 0.0)
                ref_low = ambient if ambient > 5.0 * s else _room
            except Exception:
                ref_low = _room
            span = sv - ref_low
            self._set_progress(((bt - ref_low) / span * 100.0) if span > 0 else 0.0)

            eta = _eta_minutes(bt, sv, ror) if ror is not None and ror > 0.5 else None
            self.chips.set_chips([
                (self._cl_bt,  f"{bt:.0f}°",          "#FAB387"),
                (self._cl_ror, f"{ror_chip} {trend}".strip(), "#CBA6F7"),
                (self._cl_htr, f"{heater_pct}%",      "#F9E2AF"),
                (self._cl_sv,  f"{sv:.0f}°",          "#89B4FA"),
                (self._cl_eta, self._eta_text(eta),   "#89B4FA"),
            ])

            # Banner state + coach (single advice line)
            if dist <= 0:
                self.banner.show_alert(self._tr_sv_reached, _S_OK)
                self.coach.set(self._tr_coach_ready, _S_OK)
            elif dist < 3 * s:
                self.banner.show_alert(self._tr_approaching_sv, _S_WARN)
                self.coach.set(self._tr_coach_approach, _S_WARN)
            elif dist < 10 * s:
                self.banner.show_alert(self._tr_heating_to_sv, _S_OK)
                self.coach.set(self._tr_coach_approach, _S_OK)
            elif ror is not None and ror < self._ROR_PREHEAT_LOW * s and heater_pct < 40:
                self.banner.show_alert(self._tr_heating_to_sv, _S_OK)
                self.coach.set(self._tr_coach_weak, _S_WARN)
            else:
                self.banner.show_alert(self._tr_heating_to_sv, _S_OK)
                self.coach.set(self._tr_coach_ramping, _S_OK)

            # Charge button latch on SV±2°
            if abs(dist) <= 2.0 * s:
                self._charge_btn_latched = True
            self.btn_charge.set_active(
                self._charge_btn_latched,
                style='ok' if self._charge_btn_latched else 'dim',
            )

        else:
            # ── No PID ────────────────────────────────────────────────────────
            self.hero.set_label(self._lbl_actual_bt)
            self.hero.update(
                f"{bt:.1f}",
                f"charge ≈ {charge_temp:.0f}{unit}"
                + (f"  ·  {soak_note}" if soak_note else ""),
                "#FAB387")

            span = charge_temp - _room
            self._set_progress(((bt - _room) / span * 100.0) if span > 0 else 0.0)

            self.chips.set_chips([
                (self._cl_et,   f"{et:.0f}°",          "#F38BA8"),
                (self._cl_ror,  f"{ror_chip} {trend}".strip(), "#CBA6F7"),
                (self._cl_chrg, f"{charge_temp:.0f}°", "#FAB387"),
            ])

            self.banner.show_alert(self._tr_no_pid_state, _S_OK)
            if ror is None:
                self.coach.set(self._tr_coach_normal, _S_OK)
            elif ror < 3 * s:
                self.coach.set(self._tr_coach_raise, _S_WARN)
            elif ror > 16 * s:
                self.coach.set(self._tr_coach_reduce, _S_WARN)
            else:
                self.coach.set(self._tr_coach_normal, _S_OK)

            # Enable charge near the manual charge target
            near = bt >= charge_temp - 3.0 * s
            self.btn_charge.set_active(near, style='ok' if near else 'dim')


class _DryingPage(QWidget):
    """Drying phase, layout B (low-density).

    Hero = current RoR (the steering variable). Sub-line folds band/target,
    BT and DRY END ETA (plus live Agtron when Omniflux is bound). A single
    coach line carries the advice, tinted by severity. Airflow/extraction are
    no longer separate cards — they read directly off the quick-adjust row.
    """

    _ROR_LOW  = 5.0
    _ROR_OK_L = 8.0
    _ROR_OK_H = 12.0
    _ROR_HIGH = 15.0
    _STABILIZE_SEC = 60.0
    _TP_GRACE_SEC  = 45.0

    def __init__(self, aw: ApplicationWindow):
        super().__init__()
        self.aw = aw
        self.ao = AccessOmniflux(aw)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)

        # Hero — current RoR
        self.hero = _HeroMetric(
            QApplication.translate("tilauscope_roast_assistant", "Actual RoR"), "°/min", "#A6E3A1")

        # Progress bar → DRY END (manual fill)
        prog_row = QHBoxLayout()
        prog_row.setSpacing(8)
        self._prog_outer = QFrame()
        self._prog_outer.setFixedHeight(8)
        self._prog_outer.setStyleSheet(f"background: {_BORDER}; border-radius: 4px;")
        self._prog_inner = QFrame(self._prog_outer)
        self._prog_inner.setFixedHeight(8)
        self._prog_inner.setStyleSheet("background: #CBA6F7; border-radius: 4px;")
        self._lbl_prog_val = QLabel("0 %")
        self._lbl_prog_val.setFixedWidth(40)
        self._lbl_prog_val.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._lbl_prog_val.setStyleSheet(
            f"color: #CBA6F7; font-size: 12px; font-weight: bold; {_FONT} border: none;")
        prog_row.addWidget(self._prog_outer)
        prog_row.addWidget(self._lbl_prog_val)

        # Single coach line
        self.coach = _CoachLine()

        # Quick adjust — 4 sliders
        self.quick_adjust = _QuickAdjustRow(aw, _filter_slider_configs(
            aw, getattr(aw, "_tilau_roast_context", None), [
                _slider_cfg(aw, 3), _slider_cfg(aw, 0),
                _slider_cfg(aw, 1), _slider_cfg(aw, 2),
            ]))

        # Context buttons
        _ctx_row = QHBoxLayout()
        _ctx_row.setSpacing(8)
        self.btn_cancel = _ContextButton(
            QApplication.translate("tilauscope_roast_assistant", "Cancel charge"),
            QApplication.translate("tilauscope_roast_assistant", "15s"), style='cancel')
        self.btn_cancel.clicked.connect(lambda: aw.qmc.markChargeSignal.emit(False))
        self.btn_cancel.hide()

        self.btn_dry_end = _ContextButton(
            QApplication.translate("tilauscope_roast_assistant", "Dry end"),
            QApplication.translate("tilauscope_roast_assistant", "near target"), style='dim')
        self.btn_dry_end.clicked.connect(lambda: aw.qmc.markDRYSignal.emit(False))
        self.btn_dry_end.setEnabled(False)

        self.btn_airwave = _ContextButton(
            QApplication.translate("tilauscope_roast_assistant", "AirWave"),
            QApplication.translate("tilauscope_roast_assistant", "MODE STD"), style='dim')
        self.btn_airwave.clicked.connect(lambda: _send_airwave_mode(aw, "MODE STD"))
        self.btn_airwave.setEnabled(False)

        _ctx_row.addWidget(self.btn_cancel)
        _ctx_row.addWidget(self.btn_dry_end)
        _ctx_row.addWidget(self.btn_airwave)

        # Advisor tips (roaster-physics cautions) are folded into the coach line
        # when drying is steady — no floating banner.                    ## TILAU ##
        self._advisor_tips: str = ""

        # Torréfacteur sans commandes → masque la rangée de sliders, affiche
        # les recommandations à la place (peuplées en refresh).
        self._reco = _RecoRow()
        self._readonly = _roaster_is_readonly(aw)
        if self._readonly:
            self.quick_adjust.setVisible(False)
            self._reco.show()

        layout.addWidget(self.hero)
        layout.addLayout(prog_row)
        layout.addWidget(self.coach)
        layout.addWidget(self.quick_adjust)
        layout.addWidget(self._reco)
        layout.addLayout(_ctx_row)
        layout.addStretch(1)

        # ── Translation cache (hot-path: called every 1 Hz refresh) ──────────
        self._tr_postcharge_drop                  = QApplication.translate("tilauscope_roast_assistant", "⬇ Post-charge drop — turning point ahead")
        self._tr_recovery_ror_rebuilding          = QApplication.translate("tilauscope_roast_assistant", "↩ Recovery — RoR rebuilding after turning point")
        self._tr_stabilizing_after_charge         = QApplication.translate("tilauscope_roast_assistant", "Stabilizing after charge…")
        self._tr_ramping_too_slow_raise_heater    = QApplication.translate("tilauscope_roast_assistant", "Ramping too slow — raise heater")
        self._tr_a_bit_slow_monitor_slope         = QApplication.translate("tilauscope_roast_assistant", "A bit slow — monitor slope")
        self._tpl_ideal_interval                  = QApplication.translate("tilauscope_roast_assistant", "Ideal interval {0}–{1} °/min")
        self._tr_a_bit_high                       = QApplication.translate("tilauscope_roast_assistant", "A bit high")
        self._tr_ror_too_high_reduce_heater       = QApplication.translate("tilauscope_roast_assistant", "RoR too high — reduce heater")
        self._tr_natural_honey_extended_drying    = QApplication.translate("tilauscope_roast_assistant", "natural/honey process → extended drying phase expected")
        self._tr_ror_too_low_for_estimation       = QApplication.translate("tilauscope_roast_assistant", "RoR too low for estimation")
        self._tr_stabilizing_post_tp              = QApplication.translate("tilauscope_roast_assistant", "Stabilizing post-TP…")
        self._tr_low_delta_uneven_conduction      = QApplication.translate("tilauscope_roast_assistant", "Low Delta — uneven conduction?")
        self._tr_delta_high_heating_too_strong    = QApplication.translate("tilauscope_roast_assistant", "Delta is high — heating too strong?")
        self._tr_drying_steady                    = QApplication.translate("tilauscope_roast_assistant", "Drying steady")
        self._tr_flash_drying_risk                = QApplication.translate("tilauscope_roast_assistant", "Flash drying risk — check FIR power")
        self._tr_premature_browning_detected      = QApplication.translate("tilauscope_roast_assistant", "⚠️ Premature browning detected!")
        self._tr_ror_out_of_range_check_heater    = QApplication.translate("tilauscope_roast_assistant", "⚠ RoR out of range — check heater now")
        self._tr_critical_gap_et_bt               = QApplication.translate("tilauscope_roast_assistant", "⚠ Critical Gap between ET/BT — dangerous thermic gradiant")
        # templates
        self._tpl_humid_keep_moderate             = QApplication.translate("tilauscope_roast_assistant", "humid ({0}%) → keep RoR moderate, longer drying ahead")
        self._tpl_dry_beans_flash_risk            = QApplication.translate("tilauscope_roast_assistant", "dry beans ({0}%) → watch for flash drying")
        self._tpl_low_density_heat_faster         = QApplication.translate("tilauscope_roast_assistant", "low density (ρ={0}) → heat transfer faster")
        self._tpl_dense_bean_sustained_heat       = QApplication.translate("tilauscope_roast_assistant", "dense bean (ρ={0}) → needs sustained heat")
        self._tpl_drying_longer_than_plan         = QApplication.translate("tilauscope_roast_assistant", "Drying running long: ~{0} vs plan {1} — raise heater")
        self._tpl_extended_drying                 = QApplication.translate("tilauscope_roast_assistant", "⚠ Extended drying: ~{0} vs plan {1} — baked risk, raise heater")
        # B-layout labels
        self._w_phase            = QApplication.translate("tilauscope_roast_assistant", "DRYING")
        self._w_stabilizing      = QApplication.translate("tilauscope_roast_assistant", "STABILIZING")
        self._w_in_band          = QApplication.translate("tilauscope_roast_assistant", "RoR IN BAND")
        self._w_drifting         = QApplication.translate("tilauscope_roast_assistant", "RoR DRIFTING")
        self._w_out_of_band      = QApplication.translate("tilauscope_roast_assistant", "RoR OUT OF BAND")
        self._tpl_band           = QApplication.translate("tilauscope_roast_assistant", "band {0}–{1}")
        self._tpl_target         = QApplication.translate("tilauscope_roast_assistant", "target {0}")
        self._tpl_bt_deg         = QApplication.translate("tilauscope_roast_assistant", "BT {0}°")
        self._tr_dry_end_now     = QApplication.translate("tilauscope_roast_assistant", "DRY END now")
        self._tpl_dry_end_clock  = QApplication.translate("tilauscope_roast_assistant", "DRY END ~{0}")
        self._tr_dry_end_na      = QApplication.translate("tilauscope_roast_assistant", "DRY END --")
        self._tpl_agtron         = QApplication.translate("tilauscope_roast_assistant", "Ag {0}")
        self._tpl_croc           = QApplication.translate("tilauscope_roast_assistant", "cRoC {0}")
        self._tpl_plan_delta     = QApplication.translate("tilauscope_roast_assistant", "plan {0}")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _set_progress(self, pct: float) -> None:
        pct = max(0.0, min(100.0, pct))
        total_w = self._prog_outer.width()
        if total_w > 0:
            self._prog_inner.setFixedWidth(max(8, int(total_w * pct / 100.0)))
        self._lbl_prog_val.setText(f"{pct:.0f}%")

    def _dry_end_clock(self, eta: "float | None") -> str:
        if eta is None:
            return self._tr_dry_end_na
        if eta <= 0.02:
            return self._tr_dry_end_now
        total = int(round(eta * 60.0))
        m, s = divmod(total, 60)
        return self._tpl_dry_end_clock.format(f"{m}:{s:02d}")

    # ── Public API ──────────────────────────────────────────────────────────────

    def refresh(self, bt: float, et: float, ror: float, ror_hist: list[float],
                phases: list, dry_end_temp: float, mode: str,
                bean: GreenBean|None, plan: dict|None, t_now_sec: float = 0.0,
                t_tp_sec: float = -1.0,
                crash_detector: "_RoRCrashDetector | None" = None) -> None:
        """Update the drying page (signature unchanged — driven by displayscope)."""
        trend = _ror_trend(ror_hist)
        # °F doctrine: RoR bands and temperature SPANS scale ×1.8; absolute
        # temperatures convert via fromCtoFstrict. °C path is bit-identical.
        s = 1.8 if mode == 'F' else 1.0
        _ror_lo, _ror_ok_l = self._ROR_LOW * s, self._ROR_OK_L * s
        _ror_ok_h, _ror_hi = self._ROR_OK_H * s, self._ROR_HIGH * s

        # ── Post-charge stabilization state (suppresses RoR/gap alerts) ─────────
        post_charge_dip = (ror is not None and ror <= 0)
        tp_grace_active = (
            t_tp_sec > 0 and t_now_sec > t_tp_sec
            and (t_now_sec - t_tp_sec) < self._TP_GRACE_SEC
        )
        initial_stabilize = (t_now_sec < self._STABILIZE_SEC and t_tp_sec < 0)
        stabilizing = post_charge_dip or tp_grace_active or initial_stabilize

        # ── RoR status + advice (plan target first, then fixed bands) ───────────
        ror_status = _S_OK
        ror_sub    = ""
        ror_target = _plan_ror(plan, "ROR Dry End")
        # Référence live sur la courbe planifiée : pente locale (remplace la
        # cible statique) + avance/retard en secondes. Hors zone stabilisation
        # (dip post-charge : interpolation inverse ambiguë, gérée par le helper).
        plan_delta_sec, _ror_ref = (None, None)
        if not stabilizing:
            plan_delta_sec, _ror_ref = _plan_curve_ref(plan, bt, t_now_sec)
        if _ror_ref is not None and _ror_ref > 0:
            ror_target = _ror_ref

        if stabilizing:
            if post_charge_dip:
                ror_sub = self._tr_postcharge_drop
            elif tp_grace_active:
                ror_sub = self._tr_recovery_ror_rebuilding
            else:
                ror_sub = self._tr_stabilizing_after_charge
        elif ror is not None:
            if ror_target > 0:
                ror_status, ror_sub = _ror_deviation_advice(ror, ror_target, mode, "drying",
                                                            aw=self.aw, plan=plan)
                if ror < _ror_lo:
                    ror_status, ror_sub = _S_CRIT, self._tr_ramping_too_slow_raise_heater
            else:
                if ror < _ror_lo:
                    ror_status, ror_sub = _S_CRIT, self._tr_ramping_too_slow_raise_heater
                elif ror < _ror_ok_l:
                    ror_status, ror_sub = _S_WARN, self._tr_a_bit_slow_monitor_slope
                elif ror <= _ror_ok_h:
                    ror_status, ror_sub = _S_OK, self._tpl_ideal_interval.format(
                        f"{_ror_ok_l:.0f}", f"{_ror_ok_h:.0f}")
                elif ror <= _ror_hi:
                    ror_status, ror_sub = _S_WARN, self._tr_a_bit_high
                else:
                    ror_status, ror_sub = _S_CRIT, self._tr_ror_too_high_reduce_heater

        # Bean context → tolerance notes appended to coach advice
        _hum  = float(bean.last_humidity or 0.0) if bean else 0.0
        _dens = float(bean.density or 0.0)        if bean else 0.0
        _proc = (bean.process or "").lower()      if bean else ""
        _is_natural = any(k in _proc for k in ("natural", "honey", "anaerobic"))
        grain_notes: list[str] = []
        if _hum > 13.0:
            grain_notes.append(self._tpl_humid_keep_moderate.format(f"{_hum:.1f}"))
        elif 0 < _hum < 9.0:
            grain_notes.append(self._tpl_dry_beans_flash_risk.format(f"{_hum:.1f}"))
        if 0 < _dens < 640:
            grain_notes.append(self._tpl_low_density_heat_faster.format(f"{_dens:.0f}"))
        elif _dens > 750:
            grain_notes.append(self._tpl_dense_bean_sustained_heat.format(f"{_dens:.0f}"))
        if _is_natural:
            grain_notes.append(self._tr_natural_honey_extended_drying)
        coach_text = ror_sub + ("  ·  " + "  ·  ".join(grain_notes) if grain_notes else "")

        # ── Gap ET/BT (alert only; no longer a card) ───────────────────────────
        gap_grace = (t_tp_sec < 0) or ((t_now_sec - t_tp_sec) < self._TP_GRACE_SEC)
        gap_status = _S_OK
        if not gap_grace:
            gap = et - bt
            gap_status = (_S_OK if 20 * s <= gap <= 50 * s
                          else (_S_WARN if gap < 20 * s else _S_CRIT))

        # ── ETA to DRY END ──────────────────────────────────────────────────────
        eta = _eta_minutes(bt, dry_end_temp, ror)

        # ── Projection d'overrun du séchage vs plan ─────────────────────────────
        # Symétrique au baked-risk de la page Maillard. Les durées du plan étant
        # désormais calibrées par grain (historique), dépasser la durée dry
        # planifiée de 20/40 % signale un vrai déficit d'énergie, pas un défaut
        # de grille générique.
        _dry_risk: str | None = None
        _dry_level: str = _S_WARN
        if eta is not None and not stabilizing and t_now_sec > 0:
            dry_projected_sec = t_now_sec + eta * 60.0
            dry_target_sec = _parse_plan_duration(plan, "Dry Phase")
            if dry_target_sec and dry_target_sec > 0:
                _overrun = dry_projected_sec / dry_target_sec
                if _overrun > 1.4:
                    _dry_level = _S_CRIT
                    _dry_risk = self._tpl_extended_drying.format(
                        _fmt_sec(dry_projected_sec), _fmt_sec(dry_target_sec))
                elif _overrun > 1.2:
                    _dry_risk = self._tpl_drying_longer_than_plan.format(
                        _fmt_sec(dry_projected_sec), _fmt_sec(dry_target_sec))

        # ── Live Agtron (Omniflux) — folded into the sub-line, browning alert ───
        agtron = -1.0
        color_roc: float | None = None
        premature_browning = False
        if (self.ao.omniflux and self.ao.omniflux.color_device_idx != -1
                and not stabilizing):
            agtron, color_roc = self.ao._get_omniflux_live()
            _browning_bt_max = 150.0 if mode == 'C' else fromCtoFstrict(150.0)
            if agtron > 0 and agtron < 75 and bt < _browning_bt_max:
                premature_browning = True

        # ── Hero (RoR) + status word ────────────────────────────────────────────
        if stabilizing:
            word, wcol, vcol = self._w_stabilizing, "#94A3B8", "#A6E3A1"
        elif ror_status == _S_OK:
            word, wcol, vcol = self._w_in_band, _OK, _OK
        elif ror_status == _S_WARN:
            word, wcol, vcol = self._w_drifting, _WARN, _WARN
        else:
            word, wcol, vcol = self._w_out_of_band, _CRIT, _CRIT
        # Sub-line: band/target · BT · DRY END · Agtron
        band_txt = (self._tpl_target.format(f"{ror_target:.0f}") if ror_target > 0
                    else self._tpl_band.format(f"{_ror_ok_l:.0f}", f"{_ror_ok_h:.0f}"))
        sub_parts = [band_txt, self._tpl_bt_deg.format(f"{bt:.0f}"),
                     self._dry_end_clock(None if stabilizing else eta)]
        if plan_delta_sec is not None:
            sub_parts.append(self._tpl_plan_delta.format(_fmt_plan_delta(plan_delta_sec)))
        if color_roc is not None:
            sub_parts.append(self._tpl_croc.format(f"{color_roc:+.1f}"))
        self.hero.set_label(f"{self._w_phase} · {word}", wcol)
        self.hero.update(f"{ror:.1f}" if ror is not None else "--",
                         "  ·  ".join(sub_parts), vcol, trend)

        # ── Progress → DRY END ──────────────────────────────────────────────────
        start = phases[0] if phases else 160.0
        span  = dry_end_temp - start
        self._set_progress(((bt - start) / span * 100.0) if span > 0 else 0.0)

        # ── Coach (single line, severity-tinted) ────────────────────────────────
        crash_msg = None
        if crash_detector and not stabilizing:
            crash_msg = crash_detector.check(
                ror, ror_hist, bt, target_temp=dry_end_temp,
                dt=max(0.25, self.aw.qmc.delay / 1000.0))

        if crash_msg:
            self.coach.set(crash_msg, _S_CRIT)
        elif premature_browning:
            self.coach.set(self._tr_premature_browning_detected, _S_CRIT)
        elif not stabilizing and ror_status == _S_CRIT:
            self.coach.set(self._tr_ror_out_of_range_check_heater, _S_CRIT)
        elif not stabilizing and gap_status == _S_CRIT:
            self.coach.set(self._tr_critical_gap_et_bt, _S_CRIT)
        elif _dry_risk:
            self.coach.set(_dry_risk, _dry_level)
        elif stabilizing:
            self.coach.set(coach_text, _S_OK)
        elif ror_status == _S_OK and self._advisor_tips:
            self.coach.set(self._advisor_tips, _S_OK)
        else:
            self.coach.set(coach_text, ror_status)

        # ── Quick adjust + context buttons ──────────────────────────────────────
        if self._readonly:
            self._reco.set_reco(_phase_reco_text(plan, 0))   # 0 = drying
        else:
            self.quick_adjust.refresh()

        if t_now_sec <= 15.0:
            self.btn_cancel.show()
        else:
            self.btn_cancel.hide()

        # Actif dès l'approche et AU-DELÀ de la cible (marquage manuel
        # obligatoire), warn quand le marquage est dû. S'allume avec l'alerte
        # « approaching DRY END » du graphe (signal publié, même prédiction) ;
        # l'écart de température reste un plancher de repli.
        near_dry = (not stabilizing) and (
            _coach_approaching(self.aw, "DE")
            or (dry_end_temp - bt) <= 8.0 * s
            or (eta is not None and eta <= _APPROACH_MIN))
        dry_due  = near_dry and bt >= dry_end_temp
        self.btn_dry_end.set_active(near_dry, style=('warn' if dry_due else 'ok') if near_dry else 'dim')
        _aw_on = getattr(self.aw, "bleAirwaveDevice", None) is not None
        self.btn_airwave.set_active(
            near_dry and _aw_on, style='ok' if (near_dry and _aw_on) else 'dim')


class _MaillardPage(QWidget):
    """Maillard phase, layout B (low-density).

    Hero = current RoR (steering). Sub-line folds FCs ETA, gap to FC and the
    Maillard time ratio. A single coach line carries advice, severity-tinted.
    """

    _ROR_BAKED = 3.0
    _ROR_HIGH  = 12.0

    def __init__(self, aw: ApplicationWindow):
        super().__init__()
        self.aw = aw
        self.ao = AccessOmniflux(aw)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)

        self.hero = _HeroMetric(
            QApplication.translate("tilauscope_roast_assistant", "RoR Maillard"), "°/min", "#F9E2AF")

        prog_row = QHBoxLayout()
        prog_row.setSpacing(8)
        self._prog_outer = QFrame()
        self._prog_outer.setFixedHeight(8)
        self._prog_outer.setStyleSheet(f"background: {_BORDER}; border-radius: 4px;")
        self._prog_inner = QFrame(self._prog_outer)
        self._prog_inner.setFixedHeight(8)
        self._prog_inner.setStyleSheet("background: #F9E2AF; border-radius: 4px;")
        self._lbl_prog_val = QLabel("0 %")
        self._lbl_prog_val.setFixedWidth(40)
        self._lbl_prog_val.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._lbl_prog_val.setStyleSheet(
            f"color: #F9E2AF; font-size: 12px; font-weight: bold; {_FONT} border: none;")
        prog_row.addWidget(self._prog_outer)
        prog_row.addWidget(self._lbl_prog_val)

        self.coach = _CoachLine()

        self.quick_adjust = _QuickAdjustRow(aw, _filter_slider_configs(
            aw, getattr(aw, "_tilau_roast_context", None), [
                _slider_cfg(aw, 3), _slider_cfg(aw, 0),
                _slider_cfg(aw, 1), _slider_cfg(aw, 2),
            ]))

        _ctx_row = QHBoxLayout()
        _ctx_row.setSpacing(8)
        self.btn_fcs = _ContextButton(
            QApplication.translate("tilauscope_roast_assistant", "FC start"),
            QApplication.translate("tilauscope_roast_assistant", "near FC target"), style='dim')
        self.btn_fcs.clicked.connect(lambda: aw.qmc.markFCsSignal.emit(False))
        self.btn_fcs.setEnabled(False)
        # SC start (second crack) vit sur la page DÉVELOPPEMENT — le SC survient
        # après FC end, jamais en Maillard où le bouton restait mort ; le
        # retirer d'ici libère un slot (le panneau ne tient que ~3 boutons).
        self.btn_airwave = _ContextButton(
            QApplication.translate("tilauscope_roast_assistant", "AirWave"),
            QApplication.translate("tilauscope_roast_assistant", "MODE EXT"), style='dim')
        self.btn_airwave.clicked.connect(lambda: _send_airwave_mode(aw, "MODE EXT"))
        self.btn_airwave.setEnabled(False)
        # One-tap : applique le prochain step de rampe heater au brûleur. Ne
        # s'affiche que lorsqu'un step est dû (BT proche/au-delà du seuil) et
        # que le brûleur n'y est pas déjà. Amber avant le seuil (pré-application
        # possible), vert une fois dû. L'assistant ne touche la machine QUE sur
        # ce clic (design one-tap manuel validé).
        self._aw = aw
        self._pending_ramp: "tuple[float, int] | None" = None
        self._tpl_set_burner = QApplication.translate("tilauscope_roast_assistant", "Set burner {0}%")
        self._tr_ramp_hint = QApplication.translate("tilauscope_roast_assistant", "at {0}°")
        self.btn_ramp = _ContextButton(
            QApplication.translate("tilauscope_roast_assistant", "Set burner"), "", style='dim')
        self.btn_ramp.clicked.connect(self._on_apply_ramp)
        self.btn_ramp.setVisible(False)
        _ctx_row.addWidget(self.btn_fcs)
        _ctx_row.addWidget(self.btn_ramp)
        _ctx_row.addWidget(self.btn_airwave)

        self._reco = _RecoRow()
        self._readonly = _roaster_is_readonly(aw)
        if self._readonly:
            self.quick_adjust.setVisible(False)
            self._reco.show()

        layout.addWidget(self.hero)
        layout.addLayout(prog_row)
        layout.addWidget(self.coach)
        layout.addWidget(self.quick_adjust)
        layout.addWidget(self._reco)
        layout.addLayout(_ctx_row)
        layout.addStretch(1)

        # ── Translation cache (hot-path: called every 1 Hz refresh) ──────────
        self._tr_ror_too_low_baked               = QApplication.translate("tilauscope_roast_assistant", "RoR too low → risk of baked coffee")
        self._tr_ror_high_aromas_escaping        = QApplication.translate("tilauscope_roast_assistant", "RoR is high → volatile aromas escaping")
        self._tr_ideal_decrease                  = QApplication.translate("tilauscope_roast_assistant", "Ideal decrease ✓")
        self._tr_ror_is_ok                       = QApplication.translate("tilauscope_roast_assistant", "RoR is OK")
        self._tr_ror_increasing_watch_slope      = QApplication.translate("tilauscope_roast_assistant", "RoR increasing — look after the slope")
        self._tr_high_altitude                   = QApplication.translate("tilauscope_roast_assistant", "High altitude")
        self._tr_maillard_slower                 = QApplication.translate("tilauscope_roast_assistant", "+Maillard slower")
        self._tr_floral_early_fcs                = QApplication.translate("tilauscope_roast_assistant", " · Floral profile → early FCs recommmended")
        self._tr_ror_too_low_baked_banner        = QApplication.translate("tilauscope_roast_assistant", "⚠ RoR too low — risk of baked coffee!")
        self._tr_fcs_imminent                    = QApplication.translate("tilauscope_roast_assistant", "⚠ FCs imminent — prepare next action")
        self._tpl_extended_maillard              = QApplication.translate("tilauscope_roast_assistant", "⚠ Extended Maillard ({0} proj. vs {1} plan) — baked risk, raise heat or anticipate FCs")
        self._tpl_maillard_longer_than_plan      = QApplication.translate("tilauscope_roast_assistant", "Maillard longer than plan ({0} vs {1}) — monitor RoR")
        # B-layout labels
        self._w_phase     = QApplication.translate("tilauscope_roast_assistant", "MAILLARD")
        self._w_on_track  = QApplication.translate("tilauscope_roast_assistant", "RoR ON TRACK")
        self._w_drifting  = QApplication.translate("tilauscope_roast_assistant", "RoR DRIFTING")
        self._w_baked     = QApplication.translate("tilauscope_roast_assistant", "BAKED RISK")
        self._w_na        = QApplication.translate("tilauscope_roast_assistant", "RoR --")
        self._tr_fcs_now  = QApplication.translate("tilauscope_roast_assistant", "FCs now")
        self._tr_fcs_na   = QApplication.translate("tilauscope_roast_assistant", "FCs --")
        self._tpl_fcs     = QApplication.translate("tilauscope_roast_assistant", "FCs ~{0}")
        self._tpl_gap_fc  = QApplication.translate("tilauscope_roast_assistant", "GAP {0}°")
        self._tpl_ratio   = QApplication.translate("tilauscope_roast_assistant", "ratio {0}%")
        self._tpl_plan_delta = QApplication.translate("tilauscope_roast_assistant", "plan {0}")
        self._tpl_next_step  = QApplication.translate("tilauscope_roast_assistant", "next {0}% @{1}°")

    def _set_progress(self, pct: float) -> None:
        pct = max(0.0, min(100.0, pct))
        total_w = self._prog_outer.width()
        if total_w > 0:
            self._prog_inner.setFixedWidth(max(8, int(total_w * pct / 100.0)))
        self._lbl_prog_val.setText(f"{pct:.0f}%")

    def _fcs_label(self, eta: "float | None") -> str:
        if eta is None:
            return self._tr_fcs_na
        if eta <= 0.02:
            return self._tr_fcs_now
        total = int(round(eta * 60.0))
        m, s = divmod(total, 60)
        return self._tpl_fcs.format(f"{m}:{s:02d}")

    def _on_apply_ramp(self) -> None:
        """One-tap : applique la valeur du step de rampe courant au brûleur
        (slider 3). Le step vif est mémorisé à chaque refresh (_pending_ramp) ;
        après application, la fenêtre d'inertie du coach s'ouvre d'elle-même via
        la surveillance du slider par le panneau — aucun message contradictoire."""
        if self._pending_ramp is None:
            return
        _bt_thr, heater = self._pending_ramp
        if _apply_slider_value(self._aw, _burner_slider_idx(self._aw), float(heater)):
            _logd.info(f"one-tap ramp: burner → {heater}% (threshold {_bt_thr:.0f}°)")

    def refresh(self, bt: float, ror: float, ror_hist: list[float],
                t_charge_sec: float, t_dryend_sec: float, t_now_sec: float,
                fc_temp: float, plan: dict|None,
                bean: GreenBean|None, mode: str = 'C',
                crash_detector: "_RoRCrashDetector | None" = None) -> None:
        ror_s, ror_sub = _S_OK, ""
        trend = _ror_trend(ror_hist)
        # °F : RoR et spans de température scalés ×1,8 ; chemin °C inchangé.
        s = 1.8 if mode == 'F' else 1.0
        ror_target = _plan_ror(plan, "Target ROR Maillard")
        # Référence live sur la courbe planifiée : la pente locale remplace la
        # moyenne de phase (en début de Maillard, être au-dessus de la moyenne
        # est normal — la courbe planifiée l'est aussi).
        plan_delta_sec, _ror_ref = _plan_curve_ref(plan, bt, t_now_sec)
        if _ror_ref is not None and _ror_ref > 0:
            ror_target = _ror_ref

        # RoR status + advice — PLAN-FIRST : quand une cible plan existe, elle
        # gouverne (classification relative, quantification, fenêtre ⏳). Le
        # plafond statique _ROR_HIGH ne s'applique plus qu'en repli SANS plan :
        # il interceptait la branche plan (RoR 12.5 sur cible locale ~12.6
        # lisait « aromas escaping ») et le conseil quantifié n'était jamais
        # atteint. Le filet baked (plancher absolu) reste prioritaire sur tout.
        if ror is not None:
            if ror < self._ROR_BAKED * s:
                ror_s, ror_sub = _S_CRIT, self._tr_ror_too_low_baked
            elif ror_target > 0:
                ror_s, ror_sub = _ror_deviation_advice(ror, ror_target, mode, "maillard",
                                                       aw=self.aw, plan=plan)
                if ror_s == _S_OK and trend == "↓":
                    ror_sub = self._tr_ideal_decrease + f"  (target {ror_target:.1f})"
            elif ror > self._ROR_HIGH * s:
                ror_s, ror_sub = _S_WARN, self._tr_ror_high_aromas_escaping
            else:
                ror_s = _S_OK if trend in ("↓", "→") else _S_WARN
                ror_sub = (self._tr_ideal_decrease if trend == "↓"
                           else self._tr_ror_is_ok if trend == "→"
                           else self._tr_ror_increasing_watch_slope)
            if bean and bean.altitude and bean.altitude > 1800:
                ror_sub += "  · " + self._tr_high_altitude + f" ({bean.altitude}m) → " + self._tr_maillard_slower

        # ETA / gap to FC — modèle décéléré : le RoR Maillard décline, le modèle
        # constant était optimiste et faisait SOUS-alerter la projection
        # baked-risk. Pente terminale = RoR planifié au waypoint FC START.
        _ror_at_fc = _plan_ror_at_waypoint(plan, "fc_start", 3)
        eta = _eta_minutes_decel(bt, fc_temp, _ror_smoothed(ror, ror_hist),
                                 _ror_at_fc if _ror_at_fc is not None else 0.0,
                                 scale=s)
        eta_to_fc_sec = (eta * 60.0) if (eta is not None and eta > 0) else None
        gap_fc = fc_temp - bt
        gap_s  = _S_OK if gap_fc > 5 * s else (_S_WARN if gap_fc > 2 * s else _S_CRIT)

        # Baked-risk projection (unchanged)
        _baked_risk:  str | None = None
        _baked_level: str        = _S_WARN
        if eta_to_fc_sec is not None:
            t_mai_elapsed     = t_now_sec - t_dryend_sec
            mai_projected_sec = t_mai_elapsed + eta_to_fc_sec
            mai_target_sec    = _parse_plan_duration(plan, "Maillard Phase")
            if mai_target_sec and mai_target_sec > 0:
                overrun = mai_projected_sec / mai_target_sec
                if overrun > 1.4:
                    _baked_level = _S_CRIT
                    _baked_risk  = self._tpl_extended_maillard.format(
                        _fmt_sec(mai_projected_sec), _fmt_sec(mai_target_sec))
                elif overrun > 1.2:
                    _baked_level = _S_WARN
                    _baked_risk  = self._tpl_maillard_longer_than_plan.format(
                        _fmt_sec(mai_projected_sec), _fmt_sec(mai_target_sec))

        # Maillard time ratio
        t_mai_elapsed = t_now_sec - t_dryend_sec
        t_total       = t_now_sec - t_charge_sec
        mai_ratio     = ((t_mai_elapsed / t_total) * 100) if t_total > 0 else 0

        # Hero (RoR) + status word
        if ror is None:
            word, wcol, vcol = self._w_na, "#94A3B8", "#94A3B8"
        elif ror_s == _S_CRIT:
            word, wcol, vcol = self._w_baked, _CRIT, _CRIT
        elif ror_s == _S_WARN:
            word, wcol, vcol = self._w_drifting, _WARN, _WARN
        else:
            word, wcol, vcol = self._w_on_track, _OK, "#F9E2AF"
        sub_parts = [self._fcs_label(eta),
                     self._tpl_gap_fc.format(f"{gap_fc:.0f}"),
                     self._tpl_ratio.format(f"{mai_ratio:.0f}")]
        if plan_delta_sec is not None:
            sub_parts.append(self._tpl_plan_delta.format(_fmt_plan_delta(plan_delta_sec)))
        # Prochain step de la rampe heater anticipée — les sliders vont bouger
        # « tout seuls » (alarmes BT) : l'annoncer évite la surprise opérateur.
        _ramp_next = _next_ramp_step(plan, bt)
        if _ramp_next is not None:
            sub_parts.append(self._tpl_next_step.format(
                f"{_ramp_next[1]:.0f}", f"{_ramp_next[0]:.0f}"))
        self.hero.set_label(f"{self._w_phase} · {word}", wcol)
        self.hero.update(f"{ror:.1f}" if ror is not None else "--",
                         "  ·  ".join(sub_parts), vcol, trend)

        # Progress → FC (time-based: elapsed / (elapsed + ETA))
        if eta_to_fc_sec is not None and (t_mai_elapsed + eta_to_fc_sec) > 0:
            self._set_progress(t_mai_elapsed / (t_mai_elapsed + eta_to_fc_sec) * 100.0)
        else:
            self._set_progress(100.0 if gap_fc <= 0 else 0.0)

        # Coach (single line)
        floral = ""
        if bean and bean.flavour_notes and any(
                k in bean.flavour_notes.lower()
                for k in ("floral", "jasmin", "fruit", "acidity", "acidité")):
            floral = self._tr_floral_early_fcs
        coach_text = ror_sub + floral

        crash_msg = None
        if crash_detector:
            crash_msg = crash_detector.check(ror, ror_hist, bt, target_temp=fc_temp,
                                             dt=max(0.25, self.aw.qmc.delay / 1000.0))
        if crash_msg:
            self.coach.set(crash_msg, _S_CRIT)
        elif ror_s == _S_CRIT:
            self.coach.set(self._tr_ror_too_low_baked_banner, _S_CRIT)
        elif _baked_risk:
            self.coach.set(_baked_risk, _baked_level)
        elif gap_s == _S_CRIT:
            self.coach.set(self._tr_fcs_imminent, _S_WARN)
        else:
            self.coach.set(coach_text, ror_s)

        # Quick adjust + context buttons
        if self._readonly:
            self._reco.set_reco(_phase_reco_text(plan, 1))   # 1 = Maillard
        else:
            self.quick_adjust.refresh()
        # Actif dès l'approche ET AU-DELÀ : marquer FC est une opération
        # manuelle obligatoire — le bouton ne doit jamais se réinvalider une
        # fois le FC théorique dépassé (style warn = le marquage est dû).
        # S'allume avec l'alerte « 1C approaching/imminent » du graphe (signal
        # publié, même moteur prédictif Artisan + burst acoustique) — l'ETA
        # décéléré du panneau divergeait (cible plan vs phases[2]). L'écart 10°
        # reste un plancher de repli quand le graphe ne publie rien.
        near_fc = (_coach_approaching(self.aw, "FC")
                   or (fc_temp - bt) <= 10.0 * s
                   or (eta_to_fc_sec is not None and eta_to_fc_sec <= _APPROACH_MIN * 60.0))
        fc_due  = near_fc and bt >= fc_temp
        self.btn_fcs.set_active(near_fc, style=('warn' if fc_due else 'ok') if near_fc else 'dim')
        _aw_on = getattr(self.aw, "bleAirwaveDevice", None) is not None
        self.btn_airwave.set_active(
            near_fc and _aw_on, style='ok' if (near_fc and _aw_on) else 'dim')

        # One-tap rampe heater : step « dû » = seuil le plus haut déjà atteint
        # ou proche (bt + fenêtre d'approche) que le brûleur ne tient pas encore.
        # Amber en approche, vert une fois le seuil franchi ; disparaît dès que
        # le brûleur y est posé. L'assistant n'agit QUE sur le clic.
        self._pending_ramp = None
        # Torréfacteur sans commande heater : pas de slider burner à poser, le
        # one-tap n'a pas de sens (la reco affiche déjà la valeur cible).
        if not self._readonly:
            try:
                burner_now = _read_slider_pct(self.aw, _burner_slider_idx(self.aw))
                approach = 12.0 * s
                due: "tuple[float, int] | None" = None
                for st in (plan or {}).get("Heater Ramp") or []:
                    thr, h = float(st["bt"]), int(st["heater"])
                    if thr <= bt + approach and (due is None or thr > due[0]):
                        due = (thr, h)
                if due is not None and burner_now is not None and abs(burner_now - due[1]) >= 1:
                    self._pending_ramp = due
            except (TypeError, ValueError, KeyError):
                self._pending_ramp = None
        if self._pending_ramp is not None:
            thr, h = self._pending_ramp
            self.btn_ramp.maintext = self._tpl_set_burner.format(f"{h}")
            self.btn_ramp.setText(
                self.btn_ramp.maintext + "\n" + self._tr_ramp_hint.format(f"{thr:.0f}"))
            self.btn_ramp.set_active(True, style='ok' if bt >= thr else 'warn')
            self.btn_ramp.setVisible(True)
        else:
            self.btn_ramp.setVisible(False)


class _DevelopmentPage(QWidget):
    """Development phase, layout B (low-density).

    Hero = realtime DTR (the headline development metric). Sub-line folds DTR
    target, DROP ETA, live RoR and (when available) predicted Agtron colour.
    The Agtron model drives the DROP button styling and the colour read-out.
    """

    _ROR_CRASH = 3.0

    def __init__(self, aw: ApplicationWindow):
        super().__init__()
        self.aw = aw
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)

        self.hero = _HeroMetric(
            QApplication.translate("tilauscope_roast_assistant", "DTR realtime"), "%", "#F38BA8")

        prog_row = QHBoxLayout()
        prog_row.setSpacing(8)
        self._prog_outer = QFrame()
        self._prog_outer.setFixedHeight(8)
        self._prog_outer.setStyleSheet(f"background: {_BORDER}; border-radius: 4px;")
        self._prog_inner = QFrame(self._prog_outer)
        self._prog_inner.setFixedHeight(8)
        self._prog_inner.setStyleSheet("background: #F38BA8; border-radius: 4px;")
        self._lbl_prog_val = QLabel("0 %")
        self._lbl_prog_val.setFixedWidth(40)
        self._lbl_prog_val.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._lbl_prog_val.setStyleSheet(
            f"color: #F38BA8; font-size: 12px; font-weight: bold; {_FONT} border: none;")
        prog_row.addWidget(self._prog_outer)
        prog_row.addWidget(self._lbl_prog_val)

        self.coach = _CoachLine()


        self.quick_adjust = _QuickAdjustRow(aw, _filter_slider_configs(
            aw, getattr(aw, "_tilau_roast_context", None), [
                _slider_cfg(aw, 3), _slider_cfg(aw, 0),
                _slider_cfg(aw, 1), _slider_cfg(aw, 2),
            ]))

        self.btn_drop = _ContextButton(
            QApplication.translate("tilauscope_roast_assistant", "Drop"),
            QApplication.translate("tilauscope_roast_assistant", "near drop target"), style='dim')
        self.btn_drop.clicked.connect(lambda: aw.qmc.markDropSignal.emit(False))
        # SC start (second crack) — déplacé ici depuis Maillard : le SC survient
        # en développement, après FC end. Ne s'affiche que lorsqu'il devient
        # pertinent (FC end marqué) pour ne pas encombrer les roasts clairs.
        self.btn_scs = _ContextButton(
            QApplication.translate("tilauscope_roast_assistant", "SC start"),
            QApplication.translate("tilauscope_roast_assistant", "after FC end"), style='dim')
        self.btn_scs.clicked.connect(lambda: aw.qmc.markSCsSignal.emit(False))
        self.btn_scs.setVisible(False)
        self.btn_airwave = _ContextButton(
            QApplication.translate("tilauscope_roast_assistant", "AirWave"),
            QApplication.translate("tilauscope_roast_assistant", "MODE EXT"), style='dim')
        self.btn_airwave.clicked.connect(lambda: _send_airwave_mode(aw, "MODE EXT"))
        self.btn_airwave.setEnabled(False)

        _ctx_row = QHBoxLayout()
        _ctx_row.setSpacing(8)
        _ctx_row.addWidget(self.btn_drop)
        _ctx_row.addWidget(self.btn_scs)
        _ctx_row.addWidget(self.btn_airwave)

        self._reco = _RecoRow()
        self._readonly = _roaster_is_readonly(aw)
        if self._readonly:
            self.quick_adjust.setVisible(False)
            self._reco.show()

        layout.addWidget(self.hero)
        layout.addLayout(prog_row)
        layout.addWidget(self.coach)
        layout.addWidget(self.quick_adjust)
        layout.addWidget(self._reco)
        layout.addLayout(_ctx_row)
        layout.addStretch(1)

        # ── Translation cache (hot-path: called every 1 Hz refresh) ──────────
        self._tr_ror_crash_baked_risk            = QApplication.translate("tilauscope_roast_assistant", "RoR crash → baked risk, either DROP or HEAT")
        self._tr_drop_prefix                     = QApplication.translate("tilauscope_roast_assistant", "→ DROP ")
        self._tr_ror_dev_normal                  = QApplication.translate("tilauscope_roast_assistant", "RoR DEV is normal")
        self._tr_in_target_range_envisage_drop   = QApplication.translate("tilauscope_roast_assistant", "in target range → envisage DROP")
        self._tr_ror_crash_drop_now              = QApplication.translate("tilauscope_roast_assistant", "⚠ RoR crash detected — DROP now or start heating again!")
        self._tr_drop_20sec                      = QApplication.translate("tilauscope_roast_assistant", "⏱ DROP in less than 20 seconds — get ready!")
        self._tr_dtr_target_reached              = QApplication.translate("tilauscope_roast_assistant", "DTR target reached")
        self._tr_dtr_near_target                 = QApplication.translate("tilauscope_roast_assistant", "DTR near target")
        self._tr_near_drop_target                = QApplication.translate("tilauscope_roast_assistant", "near drop target")
        self._tr_color_in_target_range           = QApplication.translate("tilauscope_roast_assistant", "color in target range")
        # B-layout labels
        self._w_phase     = QApplication.translate("tilauscope_roast_assistant", "DEVELOPMENT")
        self._w_on_target = QApplication.translate("tilauscope_roast_assistant", "DTR ON TARGET")
        self._w_drifting  = QApplication.translate("tilauscope_roast_assistant", "DTR DRIFTING")
        self._w_off       = QApplication.translate("tilauscope_roast_assistant", "DTR OFF TARGET")
        self._w_na        = QApplication.translate("tilauscope_roast_assistant", "DTR --")
        self._tr_drop_now = QApplication.translate("tilauscope_roast_assistant", "DROP now")
        self._tr_drop_na  = QApplication.translate("tilauscope_roast_assistant", "DROP --")
        self._tpl_target_pct = QApplication.translate("tilauscope_roast_assistant", "target {0}%")
        self._tpl_drop_clock = QApplication.translate("tilauscope_roast_assistant", "DROP ~{0}")
        self._tpl_ror        = QApplication.translate("tilauscope_roast_assistant", "RoR {0}")
        self._tpl_col        = QApplication.translate("tilauscope_roast_assistant", "col {0}")
        self._tpl_ag_pred    = QApplication.translate("tilauscope_roast_assistant", "~Ag {0}")
        self._tpl_dtr_proj   = QApplication.translate("tilauscope_roast_assistant", "final {0}%")

    def _set_progress(self, pct: float) -> None:
        pct = max(0.0, min(100.0, pct))
        total_w = self._prog_outer.width()
        if total_w > 0:
            self._prog_inner.setFixedWidth(max(8, int(total_w * pct / 100.0)))
        self._lbl_prog_val.setText(f"{pct:.0f}%")

    def _drop_label(self, eta: "float | None") -> str:
        if eta is None:
            return self._tr_drop_na
        if eta <= 0.02:
            return self._tr_drop_now
        total = int(round(eta * 60.0))
        m, s = divmod(total, 60)
        return self._tpl_drop_clock.format(f"{m}:{s:02d}")

    def refresh(self, bt: float, ror: float, ror_hist: list[float],
                bt_at_fcs: float,
                t_charge_sec: float, t_fcs_sec: float, t_now_sec: float,
                drop_temp: float, plan: dict|None,
                agtron_target: AgtronScale|None,
                mode: str = 'C',
                c0: float = 328.67, c_bt: float = -1.55,
                c_dtr: float = -0.06, c_wl: float = -3.61,
                weight_loss_pct: float = 14.0,
                crash_detector: "_RoRCrashDetector | None" = None) -> None:
        trend = _ror_trend(ror_hist)

        # ── Cibles RoR du plan (utilisées par l'ETA et le statut RoR) ───────────
        ror_target_avg  = _plan_ror(plan, "Target ROR Dev (Avg)")
        ror_target_drop = _plan_ror(plan, "Target ROR at Drop")

        # ── ETA DROP — modèle décéléré, entrée lissée (médiane partagée) ────────
        eta = _eta_minutes_decel(bt, drop_temp, _ror_smoothed(ror, ror_hist),
                                 ror_target_drop,
                                 scale=(1.8 if mode == 'F' else 1.0))

        # ── DTR realtime + DTR projeté au drop ─────────────────────────────────
        dtr = _dtr_realtime(t_now_sec, t_charge_sec, t_fcs_sec)
        dtr_proj = _dtr_projected(t_now_sec - t_charge_sec,
                                  t_fcs_sec - t_charge_sec, eta)
        dtr_target = 18.0
        if plan:
            try:
                dtr_target = float(plan.get("Target DTR", 18.0))
            except (TypeError, ValueError):
                pass
        if dtr is None:
            dtr_s, word, wcol, vcol = _S_OK, self._w_na, "#94A3B8", "#94A3B8"
        else:
            # Le verdict porte sur le DTR PROJETÉ au drop (là où le roast va
            # atterrir), pas sur le DTR courant qui monte mécaniquement.
            dtr_delta = (dtr_proj if dtr_proj is not None else dtr) - dtr_target
            dtr_s = (_S_OK   if abs(dtr_delta) < 2 else
                     _S_WARN if abs(dtr_delta) < 4 else _S_CRIT)
            if dtr_s == _S_OK:
                word, wcol, vcol = self._w_on_target, _OK, "#F38BA8"
            elif dtr_s == _S_WARN:
                word, wcol, vcol = self._w_drifting, _WARN, _WARN
            else:
                word, wcol, vcol = self._w_off, _CRIT, _CRIT

        # ── RoR DEV status (plan target first) ──────────────────────────────────
        # Seuil de crash relatif au plan : la fin nominale d'un dark roast
        # (RoR ≈ drop_ror planifié) ne doit plus déclencher l'alerte crash.
        ror_crash_thr = _dev_crash_threshold(ror_target_drop, mode, self._ROR_CRASH)
        ror_s, ror_sub = _S_OK, ""
        if ror is not None:
            if ror < ror_crash_thr:
                ror_s, ror_sub = _S_CRIT, self._tr_ror_crash_baked_risk
                QApplication.beep()
            elif ror_target_avg > 0:
                if eta is not None and eta < 0.5 and ror_target_drop > 0:
                    ror_s, ror_sub = _ror_deviation_advice(ror, ror_target_drop, mode, "development",
                                                           aw=self.aw, plan=plan)
                    ror_sub = self._tr_drop_prefix + ror_sub
                else:
                    ror_s, ror_sub = _ror_deviation_advice(ror, ror_target_avg, mode, "development",
                                                           aw=self.aw, plan=plan)
            else:
                ror_s, ror_sub = _S_OK, self._tr_ror_dev_normal

        # ── Agtron model (drives DROP button + read-out) ────────────────────────
        # Les coefficients (c0/c_bt/…) sont calibrés sur des BT en °C : en mode
        # °F, convertir la BT avant le modèle (sinon ~1,55 pt d'erreur par °F).
        agtron_pred = None
        if dtr is not None:
            _bt_c = fromFtoCstrict(bt) if mode == 'F' else bt
            agtron_pred = c0 + c_bt * _bt_c + c_dtr * dtr + c_wl * weight_loss_pct
            agtron_pred = max(20.0, min(130.0, agtron_pred))

        # Colour read-out uses the model prediction (0–130). The former live
        # Omniflux bias EMA was removed: the sensor's raw colour (~465) is NOT
        # on the Agtron scale (see hardware notes), so blending it against the
        # model prediction mixed incompatible scales. Reintroduce a blend only
        # once a raw → Agtron conversion exists.                     ## TILAU ##
        color_in_target = False
        col_seg: str | None = None
        if agtron_pred is not None:
            if agtron_target is not None:
                tmin = agtron_target.agtron_range.min_value
                tmax = agtron_target.agtron_range.max_value
                color_in_target = tmin <= agtron_pred <= tmax
                if color_in_target:
                    _ctint, _mark = "#A6E3A1", " ✓"
                elif agtron_pred < tmin:
                    _ctint, _mark = "#F38BA8", ""     # darker than target
                else:
                    _ctint, _mark = "#E0903B", ""     # still lighter — approaching
            else:
                _ctint, _mark = "#94A3B8", ""
            col_seg = (f"<span style='color:{_ctint};font-weight:800'>"
                       f"{self._tpl_ag_pred.format(f'{agtron_pred:.0f}')}{_mark}</span>")

        # ── Hero (DTR) + sub-line ────────────────────────────────────────────────
        # Deux lignes EXPLICITES (<br>) : cette sous-ligne est la plus longue de
        # l'app — laissée au word-wrap elle se repliait n'importe où (jusque dans
        # les chiffres au passage FC) et sa 3ᵉ ligne se faisait rogner. ## TILAU ##
        sub_parts = [self._tpl_target_pct.format(f"{dtr_target:.0f}"),
                     self._drop_label(eta)]
        if dtr_proj is not None:
            _pmark = " ✓" if abs(dtr_proj - dtr_target) < 2.0 else ""
            sub_parts.append(self._tpl_dtr_proj.format(f"{dtr_proj:.1f}") + _pmark)
        sub_parts2 = []
        if ror is not None:
            sub_parts2.append(self._tpl_ror.format(f"{ror:.1f}{(' ' + trend) if trend else ''}"))
        if col_seg:
            sub_parts2.append(col_seg)
        _sub_txt = "  ·  ".join(sub_parts)
        if sub_parts2:
            _sub_txt += "<br>" + "  ·  ".join(sub_parts2)
        self.hero.set_label(f"{self._w_phase} · {word}", wcol)
        self.hero.update(f"{dtr:.1f}" if dtr is not None else "--", _sub_txt, vcol)

        # ── Progress → DROP (BT from FC to drop target) ─────────────────────────
        span = drop_temp - bt_at_fcs
        self._set_progress(((bt - bt_at_fcs) / span * 100.0) if span > 0 else 0.0)

        # ── Coach (single line) ──────────────────────────────────────────────────
        crash_msg = None
        if crash_detector:
            # dev_mode : critère recalibré (chute/15 s — l'ancienne pente −0,8/s
            # attrapait 0/21 crashes de dev sur le corpus, banc 2026-07-11)
            crash_msg = crash_detector.check(ror, ror_hist, bt, target_temp=drop_temp,
                                             dt=max(0.25, self.aw.qmc.delay / 1000.0),
                                             dev_mode=True)
        if ror is not None and ror_s == _S_CRIT and ror < ror_crash_thr:
            self.coach.set(self._tr_ror_crash_drop_now, _S_CRIT)
        elif crash_msg:
            self.coach.set(crash_msg, _S_CRIT)
        elif eta is not None and 0 < eta <= 0.3:
            QApplication.beep()
            self.coach.set(self._tr_drop_20sec, _S_WARN)
        elif color_in_target:
            self.coach.set(self._tr_in_target_range_envisage_drop, _S_OK)
        elif ror_s == _S_CRIT:
            self.coach.set(ror_sub, _S_WARN)
        elif ror_sub:
            self.coach.set(ror_sub, ror_s)
        else:
            self.coach.set(self._tr_ror_dev_normal, _S_OK)

        # ── Quick adjust ─────────────────────────────────────────────────────────
        if self._readonly:
            self._reco.set_reco(_phase_reco_text(plan, 2))   # 2 = development
        else:
            self.quick_adjust.refresh()

        # ── DROP button — always clickable, style hints best moment ─────────────
        drop_in_target = drop_beyond = False
        if agtron_target and agtron_pred is not None:
            tmin = agtron_target.agtron_range.min_value
            tmax = agtron_target.agtron_range.max_value
            drop_in_target = tmin <= agtron_pred <= tmax
            drop_beyond    = agtron_pred < tmin
        dtr_near = False
        if not drop_in_target and not drop_beyond:
            dtr_target_val = float(plan.get("Target DTR", 18.0)) if plan else 18.0
            if dtr is not None and dtr >= dtr_target_val * 0.9:
                dtr_near = True

        if drop_in_target or drop_beyond:
            drop_style = 'warn' if drop_in_target else 'ok'
            drop_sub = (self.btn_drop.maintext + "\n" + self._tr_color_in_target_range
                        if agtron_target else self._tr_dtr_target_reached)
            self.btn_drop.set_active(True, style=drop_style)
            self.btn_drop.setText(drop_sub)
        elif dtr_near:
            self.btn_drop.set_active(True, style='warn')
            self.btn_drop.setText(self.btn_drop.maintext + "\n" + self._tr_dtr_near_target)
        else:
            self.btn_drop.set_active(True, style='dim')
            self.btn_drop.setText(self.btn_drop.maintext + "\n" + self._tr_near_drop_target)

        _aw_on = getattr(self.aw, "bleAirwaveDevice", None) is not None
        _since = _seconds_since_event(self.aw, 2)
        _aw_win = _aw_on and _since is not None and _since <= 30.0
        self.btn_airwave.set_active(_aw_win, style='ok' if _aw_win else 'dim')

        # SC start : visible seulement après FC end (le second crack n'a de sens
        # qu'à ce moment) — évite d'encombrer les roasts clairs sans SC. Reste
        # cliquable une fois affiché (marquage manuel), comme les autres jalons.
        try:
            ti = self.aw.qmc.timeindex
            fce_marked = (ti[2] > -1 and ti[3] > -1 and ti[3] > ti[2])
        except (IndexError, AttributeError):
            fce_marked = False
        self.btn_scs.setVisible(fce_marked)
        if fce_marked:
            self.btn_scs.set_active(True, style='warn')


class _CoolingPage(QWidget):
    """
    Phase COOLING — metrics displayed:
      • Current BT & ET (Landing monitoring)
      • Cooling RoR (Negative RoR to ensure effective cooling)
      • ETA to Safe Temp (estimate when it's safe to stop or reload)
      • Recommendations (Airflow max, agitator ON, next batch prep)
    """

    _SAFE_STOP_TEMP = 50.0  # Temperature below which fans can be stopped
    _NEXT_BATCH_IDLE = 160.0 # Typical target to start stabilization for next batch

    def __init__(self, aw: ApplicationWindow):
        super().__init__()
        self.aw = aw
        self.ao = AccessOmniflux(aw)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # ── Hero — BT (watched while it falls) ────────────────────────────
        self.hero = _HeroMetric(
            QApplication.translate("tilauscope_roast_assistant", "Bean Temp"), "°", "#89B4FA")

        # ── Progress — drop BT → safe target ──────────────────────────────
        self._prog_row = QHBoxLayout()
        self._prog_row.setSpacing(8)
        self._prog_outer = QFrame()
        self._prog_outer.setFixedHeight(8)
        self._prog_outer.setStyleSheet(f"background: {_BORDER}; border-radius: 4px;")
        self._prog_inner = QFrame(self._prog_outer)
        self._prog_inner.setFixedHeight(8)
        self._prog_inner.setStyleSheet(f"background: {_ACCENT}; border-radius: 4px;")
        self._lbl_prog_val = QLabel("0 %")
        self._lbl_prog_val.setFixedWidth(40)
        self._lbl_prog_val.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._lbl_prog_val.setStyleSheet(
            f"color: {_ACCENT}; font-size: 12px; font-weight: bold; {_FONT} border: none;")
        self._prog_row.addWidget(self._prog_outer)
        self._prog_row.addWidget(self._lbl_prog_val)

        # ── Single coach line ─────────────────────────────────────────────
        self.coach = _CoachLine()

        # ── Bouton Cool End ───────────────────────────────────────────────────
        self.btn_cool_end = _ContextButton(
            QApplication.translate("tilauscope_roast_assistant", "Cool end"),
            QApplication.translate("tilauscope_roast_assistant", "BT ≤ 40°"),
            style='dim',
        )
        self.btn_cool_end.clicked.connect(lambda: aw.qmc.markCoolSignal.emit(False))
        self.btn_cool_end.setEnabled(False)

        # ── Bouton Relance back-to-back (armable) ─────────────────────────────
        # Visible seulement quand un batch suivant est prévu. Sous le seuil BBP
        # (vert) : relance immédiate. Au-dessus (ambre) : le clic ARME la
        # relance — le cooling continue et la séquence part seule au
        # franchissement du seuil ; second clic = désarmement. Mode batch :
        # pas de formulaire de résultat, alog sauvé incomplet (Repair ALogs).
        self.btn_relaunch = _ContextButton(
            QApplication.translate("tilauscope_roast_assistant", "Restart batch"),
            QApplication.translate("tilauscope_roast_assistant", "save incomplete → preheat, same bean"),
            style='dim',
        )
        self._relaunch_base_text = self.btn_relaunch.text()
        self._tpl_relaunch_armed = (
            QApplication.translate("tilauscope_roast_assistant", "⏳ Armed — cancel")
            + "\n" + QApplication.translate("tilauscope_roast_assistant", "auto relaunch at {0}°"))
        self._relaunch_armed = False
        self._bbp_ready = False
        self.btn_relaunch.clicked.connect(self._on_relaunch)
        self.btn_relaunch.setVisible(False)

        # ── End of Roast summary ──────────────────────────────────────────────
        self._eor_frame = QFrame()
        self._eor_frame.setStyleSheet(
            f"QFrame {{ background: {_SURFACE}; border: 1px solid {_BORDER}; "
            f"border-radius: 8px; }} QLabel {{ border: none; background: transparent; }}"
        )
        eor_layout = QVBoxLayout(self._eor_frame)
        eor_layout.setContentsMargins(10, 8, 10, 8)
        eor_layout.setSpacing(4)

        eor_title = QLabel(QApplication.translate("tilauscope_roast_assistant", "ROAST SUMMARY"))
        eor_title.setStyleSheet(
            f"color: #585B70; font-size: 9px; font-weight: 800; {_FONT} letter-spacing: 0.8px;"
        )
        eor_layout.addWidget(eor_title)

        # 3 metrics top row
        _eor_top = QHBoxLayout()
        _eor_top.setSpacing(6)
        self._eor_dtr   = _MetricCard("DTR",   "%",   "#A6E3A1")
        self._eor_time  = _MetricCard("Total",  "min", "#89B4FA")
        self._eor_color = _MetricCard("Agtron", "",    "#F9E2AF")
        self._eor_dtr.setFixedHeight(70)
        self._eor_time.setFixedHeight(70)
        self._eor_color.setFixedHeight(70)
        _eor_top.addWidget(self._eor_dtr)
        _eor_top.addWidget(self._eor_time)
        _eor_top.addWidget(self._eor_color)
        eor_layout.addLayout(_eor_top)

        # Phase breakdown rows
        def _eor_row(lbl: str) -> tuple[QLabel, QLabel]:
            row = QHBoxLayout()
            row.setSpacing(4)
            l = QLabel(lbl)
            l.setStyleSheet(f"color: #7F849C; font-size: 10px; {_FONT}")
            v = QLabel("--")
            v.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            v.setStyleSheet(f"color: #CDD6F4; font-size: 10px; font-weight: 700; {_FONT}")
            v.setTextFormat(Qt.TextFormat.RichText)
            row.addWidget(l)
            row.addStretch()
            row.addWidget(v)
            eor_layout.addLayout(row)
            sep = QFrame(); sep.setFixedHeight(1)
            sep.setStyleSheet(f"background: {_BORDER}; border: none;")
            eor_layout.addWidget(sep)
            return l, v

        _, self._eor_dry_val   = _eor_row(QApplication.translate("tilauscope_roast_assistant", "Dry"))
        _, self._eor_mai_val   = _eor_row(QApplication.translate("tilauscope_roast_assistant", "Maillard"))
        _, self._eor_dev_val   = _eor_row(QApplication.translate("tilauscope_roast_assistant", "Dev"))
        _, self._eor_dtr2_val  = _eor_row(QApplication.translate("tilauscope_roast_assistant", "DTR vs target"))
        _, self._eor_col2_val  = _eor_row(QApplication.translate("tilauscope_roast_assistant", "Color vs target"))
        _, self._eor_fcdrop_val= _eor_row(QApplication.translate("tilauscope_roast_assistant", "FC · Drop BT"))

        # ── Colour → next plan (F1 bench integration) ── ## TILAU ## ───────────
        # Announces (display only) the correction the colour→drop_bt learning
        # will apply to the NEXT plan, translated into DTR language for
        # readability. Measured colour (whole/ground) is used when present,
        # else the model prediction; hidden entirely when neither exists.
        self._eor_color_next_box = QWidget()
        _cn_v = QVBoxLayout(self._eor_color_next_box)
        _cn_v.setContentsMargins(0, 4, 0, 0)
        _cn_v.setSpacing(2)
        _cn_title = QLabel(
            QApplication.translate("tilauscope_roast_assistant", "COLOUR → NEXT PLAN"))
        _cn_title.setStyleSheet(
            f"color: #585B70; font-size: 9px; font-weight: 800; {_FONT} letter-spacing: 0.8px;")
        _cn_v.addWidget(_cn_title)
        self._eor_color_next_line = QLabel("--")
        self._eor_color_next_line.setWordWrap(True)
        self._eor_color_next_line.setTextFormat(Qt.TextFormat.RichText)
        self._eor_color_next_line.setStyleSheet(f"color: #BAC2DE; font-size: 10px; {_FONT}")
        _cn_v.addWidget(self._eor_color_next_line)
        eor_layout.addWidget(self._eor_color_next_box)
        self._eor_color_next_box.hide()

        # ── Trajectory vs plan (per-phase, time-normalised) ───────────────────
        # Compares the actual BT shape to the planned bt_plan curve inside each
        # phase (drying / maillard / development), independent of phase duration.
        # Computed once at DROP; hidden when no plan curve is available.
        self._eor_traj_box = QWidget()
        _traj_v = QVBoxLayout(self._eor_traj_box)
        _traj_v.setContentsMargins(0, 2, 0, 0)
        _traj_v.setSpacing(4)

        _traj_title = QLabel(
            QApplication.translate("tilauscope_roast_assistant", "TRAJECTORY vs PLAN"))
        _traj_title.setStyleSheet(
            f"color: #585B70; font-size: 9px; font-weight: 800; {_FONT} letter-spacing: 0.8px;")
        _traj_v.addWidget(_traj_title)

        self._eor_traj_verdict = QLabel("--")
        self._eor_traj_verdict.setWordWrap(True)
        self._eor_traj_verdict.setStyleSheet(f"color: #BAC2DE; font-size: 10px; {_FONT}")
        _traj_v.addWidget(self._eor_traj_verdict)

        def _traj_row(lbl: str) -> tuple[QLabel, QLabel]:
            row = QHBoxLayout()
            row.setSpacing(6)
            dot = QLabel("●")
            dot.setStyleSheet(f"color: {_BORDER}; font-size: 10px; {_FONT}")
            l = QLabel(lbl)
            l.setStyleSheet(f"color: #7F849C; font-size: 10px; {_FONT}")
            v = QLabel("--")
            v.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            v.setStyleSheet(f"color: #CDD6F4; font-size: 10px; font-weight: 700; {_FONT}")
            row.addWidget(dot)
            row.addWidget(l)
            row.addStretch()
            row.addWidget(v)
            _traj_v.addLayout(row)
            return dot, v

        self._eor_traj_dry_dot, self._eor_traj_dry_val = _traj_row(
            QApplication.translate("tilauscope_roast_assistant", "Drying"))
        self._eor_traj_mai_dot, self._eor_traj_mai_val = _traj_row(
            QApplication.translate("tilauscope_roast_assistant", "Maillard"))
        self._eor_traj_dev_dot, self._eor_traj_dev_val = _traj_row(
            QApplication.translate("tilauscope_roast_assistant", "Development"))

        eor_layout.addWidget(self._eor_traj_box)
        self._eor_traj_box.hide()

        # Action buttons
        _eor_acts = QHBoxLayout()
        _eor_acts.setSpacing(8)
        self._eor_btn_notes = QPushButton(
            QApplication.translate("tilauscope_roast_assistant", "Notes"))
        self._eor_btn_notes.setStyleSheet(
            f"QPushButton {{ border: 1px solid {_BORDER}; border-radius: 6px; "
            f"color: #CDD6F4; font-size: 10px; font-weight: 700; {_FONT} "
            f"padding: 7px 8px; background: transparent; }}"
            f"QPushButton:hover {{ background: {_SURFACE}; }}"
        )
        self._eor_btn_result = QPushButton(
            QApplication.translate("tilauscope_roast_assistant", "Result form"))
        self._eor_btn_result.setStyleSheet(
            f"QPushButton {{ border: 1.5px solid #CBA6F7; border-radius: 6px; "
            f"color: #CBA6F7; font-size: 10px; font-weight: 700; {_FONT} "
            f"padding: 7px 8px; background-color: rgba(203,166,247,0.08); }}"
            f"QPushButton:hover {{ background-color: rgba(203,166,247,0.18); }}"
        )
        # Veto d'apprentissage : roast raté « propre » (stall récupéré, jalon
        # mal marqué) qui passerait les filtres qualité — le toggle pose
        # qmc.tilau_exclude_learning, persisté dans l'alog au save, et
        # l'analyse historique du plan saute le fichier pour toujours.
        self._eor_btn_exclude = QPushButton(
            QApplication.translate("tilauscope_roast_assistant", "🚫 Exclude from learning"))
        self._eor_btn_exclude.setCheckable(True)
        self._eor_btn_exclude.setStyleSheet(
            f"QPushButton {{ border: 1px solid {_BORDER}; border-radius: 6px; "
            f"color: #6C7086; font-size: 10px; font-weight: 700; {_FONT} "
            f"padding: 7px 8px; background: transparent; }}"
            f"QPushButton:hover {{ background: {_SURFACE}; }}"
            f"QPushButton:checked {{ border: 1.5px solid {_CRIT}; color: {_CRIT}; "
            f"background-color: rgba(243,139,168,0.10); }}"
        )
        _eor_acts.addWidget(self._eor_btn_notes)
        _eor_acts.addWidget(self._eor_btn_result)
        _eor_acts.addWidget(self._eor_btn_exclude)
        eor_layout.addLayout(_eor_acts)

        # Banner kept (hidden) for backward-compat; the coach owns alerts.
        self.banner = _AlertBanner()
        self.banner.hide()

        layout.addWidget(self.hero)
        layout.addLayout(self._prog_row)
        layout.addWidget(self.coach)
        layout.addWidget(self.btn_cool_end)
        layout.addWidget(self.btn_relaunch)
        layout.addWidget(self._eor_frame)

        # ── Translation cache (hot-path: called every 1 Hz refresh) ──────────
        self._tr_effective_cooling               = QApplication.translate("tilauscope_roast_assistant", "Effective cooling")
        self._tr_slow_cooling_increase_airflow   = QApplication.translate("tilauscope_roast_assistant", "Slow cooling - Increase airflow")
        self._tr_reached                         = QApplication.translate("tilauscope_roast_assistant", "Reached")
        self._tr_until                           = QApplication.translate("tilauscope_roast_assistant", "Until")
        self._tr_beans_not_cooling_fire          = QApplication.translate("tilauscope_roast_assistant", "⚠ BEANS NOT COOLING - RISK OF FIRE")
        self._tr_target_reached_proceed          = QApplication.translate("tilauscope_roast_assistant", "✅ Target reached. You can proceed.")
        # template
        self._tpl_back_to_back                   = QApplication.translate("tilauscope_roast_assistant", "🔄 **Back-to-Back Mode**:\nKeep airflow high until ET drops. Once BT reaches ~{0}°C, switch to Preheat/Stabilization phase for the next batch.")
        # B-layout labels + condensed coach lines
        self._w_phase         = QApplication.translate("tilauscope_roast_assistant", "COOLING")
        self._w_in_progress   = QApplication.translate("tilauscope_roast_assistant", "IN PROGRESS")
        self._w_safe          = QApplication.translate("tilauscope_roast_assistant", "SAFE")
        self._w_not_cooling   = QApplication.translate("tilauscope_roast_assistant", "NOT COOLING")
        self._tr_safe_na      = QApplication.translate("tilauscope_roast_assistant", "SAFE --")
        self._tr_safe_now     = QApplication.translate("tilauscope_roast_assistant", "SAFE now")
        self._tpl_safe_clock  = QApplication.translate("tilauscope_roast_assistant", "SAFE ~{0}")
        self._tpl_et_deg      = QApplication.translate("tilauscope_roast_assistant", "ET {0}°")
        self._tpl_cool_ror    = QApplication.translate("tilauscope_roast_assistant", "RoR {0} °/min")
        self._tr_coach_shutdown   = QApplication.translate("tilauscope_roast_assistant", "Open drum door & cooling tray, keep drum spinning. Don't cut main power until BT < 50°.")
        self._tpl_coach_back2back = QApplication.translate("tilauscope_roast_assistant", "Keep airflow high until ET drops; at ~{0}° switch to preheat for the next batch.")
        # _soak_hint() runs on every refresh() tick during COOLING — must not
        # re-translate per tick.
        self._tpl_soak_hint = QApplication.translate(
            "tilauscope_roast_assistant", "next batch: charge {0}° (heat soak) — neutral in ~{1} min")
        # Trajectory-vs-plan verdicts (end-of-roast summary)
        self._tr_traj_drying      = QApplication.translate("tilauscope_roast_assistant", "Drying")
        self._tr_traj_maillard    = QApplication.translate("tilauscope_roast_assistant", "Maillard")
        self._tr_traj_dev         = QApplication.translate("tilauscope_roast_assistant", "Development")
        self._tr_traj_inplan      = QApplication.translate("tilauscope_roast_assistant", "on plan")
        self._tr_traj_hotter      = QApplication.translate("tilauscope_roast_assistant", "hotter")
        self._tr_traj_cooler      = QApplication.translate("tilauscope_roast_assistant", "cooler")
        self._tr_traj_good        = QApplication.translate("tilauscope_roast_assistant", "Trajectory well held across all phases.")
        self._tpl_traj_slight     = QApplication.translate("tilauscope_roast_assistant", "Well held — slight drift in {0}.")
        self._tpl_traj_off        = QApplication.translate("tilauscope_roast_assistant", "Marked drift in {0} ({1}).")
        # Colour → next plan (F1) ── ## TILAU ##
        self._tpl_color_ontarget  = QApplication.translate(
            "tilauscope_roast_assistant", "🎨 Colour {0} · target {1} (±{2}) — on target, next plan unchanged")
        self._tpl_color_next      = QApplication.translate(
            "tilauscope_roast_assistant", "🎨 Colour {0} · target {1} (±{2}) — {3} by {4} pts"
                "<br>→ Next plan: <b>{5} °C at drop</b> · ≈ {6} pt DTR")
        self._tr_color_too_light  = QApplication.translate("tilauscope_roast_assistant", "too light")
        self._tr_color_too_dark   = QApplication.translate("tilauscope_roast_assistant", "too dark")

    def _set_progress(self, pct: float) -> None:
        pct = max(0.0, min(100.0, pct))
        total_w = self._prog_outer.width()
        if total_w > 0:
            self._prog_inner.setFixedWidth(max(8, int(total_w * pct / 100.0)))
        self._lbl_prog_val.setText(f"{pct:.0f}%")

    def _safe_label(self, eta: "float | None") -> str:
        if eta is None:
            return self._tr_safe_na
        if eta <= 0.02:
            return self._tr_safe_now
        total = int(round(eta * 60.0))
        m, sec = divmod(total, 60)
        return self._tpl_safe_clock.format(f"{m}:{sec:02d}")

    def refresh(self, bt: float, et: float, ror: float, ror_hist: list[float],
                next_batch_planned: bool = False,
                plan: dict | None = None,
                agtron_target: "AgtronScale | None" = None,
                agtron_pred: float | None = None) -> None:
        """
        Updates the Cooling page.
        ror: expect negative values during cooling.
        """
        trend = _ror_trend(ror_hist)
        mode_c = (self.aw.qmc.mode == 'C')

        # Thresholds (mode-aware)
        ceiling_bt  = 220.0 if mode_c else fromCtoFstrict(220.0)
        # RoR sont des DELTAS : scaling ×1.8, pas de conversion d'offset.
        # (fromCtoFstrict(-5) donnait +23 °F → l'alerte "not cooling" était
        # inatteignable en °F, et le seuil d'ETA était faux.)
        warm_ror    = -5.0  if mode_c else -5.0 * 1.8
        ror_min     = -1.0  if mode_c else -1.0 * 1.8
        bbp_temp    = 160.0 if mode_c else fromCtoFstrict(160.0)
        target_temp = self._NEXT_BATCH_IDLE if next_batch_planned else self._SAFE_STOP_TEMP
        target_temp = target_temp if mode_c else fromCtoFstrict(target_temp)

        not_cooling = (bt > ceiling_bt and ror > warm_ror)
        is_safe     = (bt <= target_temp)

        # ETA to target (negative slope only)
        eta = None
        if ror < ror_min:
            d = bt - target_temp
            if d > 0:
                eta = d / abs(ror)

        # Hero (BT) + status word
        if not_cooling:
            word, wcol, vcol = self._w_not_cooling, _CRIT, _CRIT
        elif is_safe:
            word, wcol, vcol = self._w_safe, _OK, _OK
        else:
            word, wcol, vcol = self._w_in_progress, _ACCENT, _ACCENT
        sub = "  ·  ".join([
            self._tpl_et_deg.format(f"{et:.0f}"),
            self._tpl_cool_ror.format(f"{ror:.0f}"),
            self._safe_label(eta),
        ])
        self.hero.set_label(f"{self._w_phase} · {word}", wcol)
        self.hero.update(f"{bt:.1f}", sub, vcol, trend)

        # Progress: drop BT → safe target (fills as it cools)
        drop_bt = None
        try:
            ti = self.aw.qmc.timeindex
            if ti[6] > -1:
                drop_bt = float(self.aw.qmc.temp2[ti[6]])
        except (IndexError, TypeError, AttributeError):
            drop_bt = None
        start = drop_bt if (drop_bt and drop_bt > target_temp) else max(bt, ceiling_bt)
        span  = start - target_temp
        self._set_progress(((start - bt) / span * 100.0) if span > 0 else 0.0)

        # Coach (single line) — alerts win, then guidance
        if not_cooling:
            self.coach.set(self._tr_beans_not_cooling_fire, _S_CRIT)
        elif is_safe:
            self.coach.set(self._tr_target_reached_proceed, _S_OK)
        elif next_batch_planned:
            self.coach.set(
                self._tpl_coach_back2back.format(f"{bbp_temp:.0f}") + self._soak_hint(),
                _S_OK)
        else:
            self.coach.set(self._tr_coach_shutdown, _S_OK)

        # ── C : Bouton Cool end ───────────────────────────────────────────────
        safe_temp = 40.0 if self.aw.qmc.mode == 'C' else fromCtoFstrict(40.0)
        cool_ready = bt <= safe_temp
        self.btn_cool_end.set_active(cool_ready, style='purple' if cool_ready else 'dim')

        # ── Relance back-to-back (armable) ────────────────────────────────────
        # Sous le seuil BBP : verte, relance immédiate au clic. Au-dessus :
        # ambre, le clic arme — au franchissement du seuil la séquence part
        # seule (STOP sans formulaire, sauvegarde silencieuse, RESET, preheat).
        self.btn_relaunch.setVisible(next_batch_planned)
        if next_batch_planned:
            self._bbp_ready = bt <= bbp_temp
            if self._relaunch_armed and self._bbp_ready:
                # Seuil franchi pendant l'armement → tir automatique (one-shot),
                # DIFFÉRÉ hors du cycle de refresh : la séquence STOP arrête
                # l'assistant et manipule le stack — pas de réentrance ici.
                self._relaunch_armed = False
                self.btn_relaunch.setText(self._relaunch_base_text)
                QTimer.singleShot(0, self._trigger_relaunch)
            elif self._relaunch_armed:
                self.btn_relaunch.set_active(True, style='warn')
                self.btn_relaunch.setText(self._tpl_relaunch_armed.format(f"{bbp_temp:.0f}"))
            else:
                self.btn_relaunch.set_active(True, style='ok' if self._bbp_ready else 'warn')
                self.btn_relaunch.setText(self._relaunch_base_text)
        else:
            self._relaunch_armed = False

        # ── C : End of Roast summary ──────────────────────────────────────────
        self._populate_eor_summary(plan, agtron_target, agtron_pred)

    def _on_relaunch(self) -> None:
        """Clic sur « Restart batch » : désarme si armé ; relance immédiate
        si la BT est déjà sous le seuil BBP ; sinon ARME — la relance partira
        automatiquement au franchissement du seuil (voir refresh)."""
        if self._relaunch_armed:
            self._relaunch_armed = False
            self.btn_relaunch.setText(self._relaunch_base_text)
            return
        if self._bbp_ready:
            self._trigger_relaunch()
        else:
            self._relaunch_armed = True

    def _trigger_relaunch(self) -> None:
        """Relance back-to-back : délègue l'orchestration à TilauScope
        (STOP sans formulaire, sauvegarde silencieuse de l'alog incomplet,
        RESET, ré-injection — même grain, même charge verte — START preheat)."""
        try:
            main = getattr(self.aw, 'tilauscope_main', None)
            if main is not None:
                # Le panneau force son redémarrage au prochain START quel que
                # soit le niveau opérateur (en Standard/Expert l'auto-start
                # n'existe pas) — même grain, plan neuf avec heat-soak.
                panel = getattr(main, 'roast_assistant', None)
                if panel is not None:
                    panel._relaunch_requested = True
                main.relaunch_batch()
        except Exception as e:  # pylint: disable=broad-except
            _logd.warning(f"relaunch batch failed: {e}")

    def _soak_hint(self) -> str:
        """Complément back-to-back du coach cooling : correction heat-soak que
        subirait le prochain plan à cet instant, et horizon de neutralité
        (correction < 1 °C). Chaîne vide si indisponible (batch 1, pas de
        contexte machine) — le message BBP de base reste inchangé."""
        try:
            t = getattr(self.aw, "_tilau_last_drop_wall", None)
            rctx = getattr(self.aw, "_tilau_roast_context", None)
            if not t or rctx is None:
                return ""
            mins = (time.time() - float(t)) / 60.0
            m = float(getattr(rctx, "thermal_mass_index", 0.65) or 0.65)
            r = float(getattr(rctx, "heat_retention_index", 0.65) or 0.65)
            dcharge, _dh, tau = heat_soak_correction(mins, m, r)
            if dcharge >= 0.0:
                return ""
            s = 1.8 if self.aw.qmc.mode == 'F' else 1.0
            # Horizon de neutralité : t où la correction passe sous 1 °C.
            k = 4.0 + 6.0 * ((m + r) / 2.0)
            remain = max(0.0, tau * math.log(k) - mins)
            return "  ·  " + self._tpl_soak_hint.format(
                f"{dcharge * s:+.1f}", f"{remain:.0f}")
        except Exception:  # pylint: disable=broad-except
            return ""

    def _populate_eor_summary(
        self,
        plan: dict | None,
        agtron_target: "AgtronScale | None",
        agtron_pred: float | None,
    ) -> None:
        """Remplit le résumé end-of-roast depuis qmc et le plan."""
        qmc  = self.aw.qmc
        ti   = qmc.timeindex
        tx   = qmc.timex
        mode = qmc.mode

        # Lecture absolue des timestamps — pas de référence CHARGE
        # pour éviter les problèmes d'indices -1 ou 0 selon le simulateur
        def _abs(idx: int) -> float:
            try:
                i = ti[idx]
                return float(tx[i]) if i > 0 and i < len(tx) else -1.0
            except (IndexError, TypeError):
                return -1.0

        abs_charge = _abs(0)
        abs_dryend = _abs(1)
        abs_fcs    = _abs(2)
        abs_drop   = _abs(6)

        # Si CHARGE non marqué on ne peut rien calculer
        if abs_charge < 0:
            return

        # Durées relatives depuis CHARGE (en secondes)
        t_dryend = (abs_dryend - abs_charge) if abs_dryend > 0 else 0.0
        t_fcs    = (abs_fcs    - abs_charge) if abs_fcs    > 0 else 0.0
        t_drop   = (abs_drop   - abs_charge) if abs_drop   > 0 else 0.0

        # t_total : DROP si disponible, sinon dernière valeur enregistrée
        if t_drop > 0:
            t_total = t_drop
        elif tx and abs_charge > 0:
            t_total = float(tx[-1]) - abs_charge
        else:
            t_total = 0.0

        _logd.debug(
            f"EOR summary: ti={list(ti[:8])} "
            f"t_dryend={t_dryend:.1f} t_fcs={t_fcs:.1f} "
            f"t_drop={t_drop:.1f} t_total={t_total:.1f}"
        )

        def _fmt(secs: float) -> str:
            if secs <= 0:
                return "--"
            m, s = divmod(int(secs), 60)
            return f"{m}:{s:02d}"

        # DTR
        dtr_val = None
        if t_total > 0 and t_fcs > 0:
            dev_secs = t_total - t_fcs
            dtr_val = (dev_secs / t_total) * 100.0
        dtr_target = float(plan.get("Target DTR", 18.0)) if plan else 18.0

        # Phase durations — toutes relatives au CHARGE (déjà soustrait dans abs_x - abs_charge)
        dry_secs = t_dryend if t_dryend > 0 else 0.0
        mai_secs = (t_fcs - t_dryend) if t_fcs > 0 and t_dryend > 0 else 0.0
        dev_secs = (t_total - t_fcs)   if t_total > 0 and t_fcs > 0 else 0.0

        def _pct(part: float) -> str:
            if t_total > 0 and part > 0:
                return f" · {part/t_total*100:.0f}%"
            return ""

        # Top metrics
        if dtr_val is not None:
            status = _S_OK if abs(dtr_val - dtr_target) < 2 else (_S_WARN if abs(dtr_val - dtr_target) < 4 else _S_CRIT)
            self._eor_dtr.update(f"{dtr_val:.1f}", f"target {dtr_target:.0f}%", status)
        else:
            self._eor_dtr.update("--", "")

        total_min = t_total / 60.0 if t_total > 0 else 0.0
        self._eor_time.update(f"{_fmt(t_total)}", "")

        if agtron_pred is not None:
            col_status = _S_OK
            col_sub = ""
            if agtron_target:
                tmin, tmax = agtron_target.agtron_range.min_value, agtron_target.agtron_range.max_value
                if agtron_pred < tmin:
                    col_sub = f"Δ +{tmin - agtron_pred:.0f} pts dark"
                    col_status = _S_WARN
                elif agtron_pred > tmax:
                    col_sub = f"Δ +{agtron_pred - tmax:.0f} pts light"
                    col_status = _S_WARN
            self._eor_color.update(f"~{agtron_pred:.0f}", col_sub, col_status)
        else:
            self._eor_color.update("--", "")

        # Phase rows
        self._eor_dry_val.setText(f"{_fmt(dry_secs)}{_pct(dry_secs)}")
        self._eor_mai_val.setText(f"{_fmt(mai_secs)}{_pct(mai_secs)}")
        self._eor_dev_val.setText(f"{_fmt(dev_secs)}{_pct(dev_secs)}")

        if dtr_val is not None:
            delta = dtr_val - dtr_target
            col = "#F38BA8" if abs(delta) >= 4 else ("#F9E2AF" if abs(delta) >= 2 else "#A6E3A1")
            self._eor_dtr2_val.setText(
                f"<span style='color:{col}'>{dtr_val:.1f}%  Δ{delta:+.1f}%</span>")
        else:
            self._eor_dtr2_val.setText("--")

        if agtron_pred is not None and agtron_target:
            tmin, tmax = agtron_target.agtron_range.min_value, agtron_target.agtron_range.max_value
            mid = (tmin + tmax) / 2
            delta = agtron_pred - mid
            col = "#F9E2AF" if abs(delta) > 5 else "#A6E3A1"
            self._eor_col2_val.setText(
                f"<span style='color:{col}'>{agtron_target.name}  Δ{delta:+.0f}</span>")

        # FC + Drop BT
        try:
            bt_fc   = float(qmc.temp2[ti[2]]) if ti[2] > -1 else 0.0
            bt_drop = float(qmc.temp2[ti[6]]) if ti[6] > -1 else 0.0
            self._eor_fcdrop_val.setText(f"{bt_fc:.1f}° · {bt_drop:.1f}°")
        except (IndexError, TypeError):
            self._eor_fcdrop_val.setText("--")

        # Colour → next plan announcement (F1 bench integration) ── ## TILAU ##
        self._update_color_next_plan(agtron_target, agtron_pred, qmc)

        # Trajectory vs plan (per-phase, time-normalised)
        self._update_plan_adherence(plan, qmc, ti, tx)

    def _update_color_next_plan(
        self,
        agtron_target: "AgtronScale | None",
        agtron_pred: float | None,
        qmc,
    ) -> None:
        """Bloc EOR « couleur → prochain plan » (F1). AFFICHAGE SEUL — le canal
        correctif réel reste l'apprentissage couleur→drop_bt du plan (−0,323 °C/pt,
        [[project-roast-plan-map]]) ; ici on TRADUIT l'écart couleur du roast en
        langage lisible (°C au drop + pt DTR via 1,5 pt Agtron/pt DTR, étude 3).

        Couleur mesurée (whole/ground) prioritaire ; à défaut la prédiction du
        modèle (consistante au drop). Sans cible ni couleur : bloc caché
        (Q-F1 : « si l'info n'est pas là, on saute le sujet »).
        """
        box = self._eor_color_next_box
        if agtron_target is None:
            box.hide()
            return

        # 1) couleur du roast : mesurée d'abord (ground puis whole), sinon prédite
        colour_val: float | None = None
        is_measured = False
        try:
            ground = float(getattr(qmc, "ground_color", 0) or 0)
            whole  = float(getattr(qmc, "whole_color",  0) or 0)
            raw = ground if ground > 0 else (whole if whole > 0 else 0.0)
            if raw > 0:
                csys = qmc.color_systems[qmc.color_system_idx]
                colour_val = self._average_color_in_agtron(float(raw), csys)
                is_measured = True
        except (IndexError, TypeError, ValueError, AttributeError):
            colour_val = None
        if colour_val is None:
            colour_val = agtron_pred
        if colour_val is None:
            box.hide()
            return

        tmin = agtron_target.agtron_range.min_value
        tmax = agtron_target.agtron_range.max_value
        mid  = (tmin + tmax) / 2.0
        band = max(0.0, (tmax - tmin) / 2.0)
        tag  = "" if is_measured else "~"
        val_txt = f"{tag}{colour_val:.0f}"

        # 2) écart depuis le centre de cible (Agtron ↑ = plus clair). No
        # universal colour-to-DROP-temperature correction is validated.
        miss = colour_val - mid

        if tmin <= colour_val <= tmax:
            self._eor_color_next_line.setText(
                "<span style='color:#A6E3A1'>"
                + self._tpl_color_ontarget.format(val_txt, f"{mid:.0f}", f"{band:.0f}")
                + "</span>")
            box.show()
            return

        # 3) correction directionnelle annoncée
        dir_txt = self._tr_color_too_light if miss > 0 else self._tr_color_too_dark
        col = "#F9E2AF"
        self._eor_color_next_line.setText(
            f"<span style='color:{col}'>"
            + QApplication.translate(
                "tilauscope",
                "Measured colour {0} is {1} by {2} Agtron points. Review development time and the live curve; no universal DROP-temperature correction is applied.").format(
                    val_txt, dir_txt, f"{abs(miss):.0f}")
            + "</span>")
        box.show()

    def _update_plan_adherence(self, plan: dict | None, qmc, ti, tx) -> None:
        """
        Per-phase mean BT deviation from the planned bt_plan curve, time-normalised
        within each phase (compares the curve *shape*, not the phase duration).
        Computed once on entering the DROP page. Hidden when no plan curve exists.
        """
        box = self._eor_traj_box
        try:
            pc = plan.get("bt_plan_curve") if plan else None
            if not pc:
                box.hide(); return
            pc_t  = pc.get("time_min") or []   # minutes from CHARGE
            pc_bt = pc.get("bt_plan")  or []
            wps   = pc.get("waypoints") or []
            if len(pc_t) < 2 or len(pc_t) != len(pc_bt) or len(wps) < 6:
                box.hide(); return

            # Seuils d'adhérence ADAPTATIFS (unité native, calibrés par la
            # confiance de l'historique du plan) ; repli 3/7° sans bloc.
            _tols = plan.get("Plan Tolerances") or {}
            try:
                tol_ok   = float(_tols.get("adher_ok", 3.0))
                tol_warn = float(_tols.get("adher_warn", 7.0))
            except (TypeError, ValueError):
                tol_ok, tol_warn = 3.0, 7.0

            temp2 = qmc.temp2
            n = min(len(temp2), len(tx))
            i_charge, i_dry, i_fc, i_drop = ti[0], ti[1], ti[2], ti[6]

            # plan phase boundaries (minutes) — resolved by stable waypoint key
            # (translation-safe, survives waypoint insertion); positional fallback
            # covers plans generated before the "key" field existed.
            _wp_c, _wp_d = _waypoint(wps, "charge", 0), _waypoint(wps, "dry_end", 2)
            _wp_f, _wp_p = _waypoint(wps, "fc_start", 3), _waypoint(wps, "drop", 5)
            if None in (_wp_c, _wp_d, _wp_f, _wp_p):
                box.hide(); return
            p_charge = float(_wp_c["time_min"])
            p_dry    = float(_wp_d["time_min"])
            p_fc     = float(_wp_f["time_min"])
            p_drop   = float(_wp_p["time_min"])

            phases = [
                (i_charge, i_dry,  p_charge, p_dry,  self._eor_traj_dry_dot, self._eor_traj_dry_val, self._tr_traj_drying),
                (i_dry,    i_fc,   p_dry,    p_fc,   self._eor_traj_mai_dot, self._eor_traj_mai_val, self._tr_traj_maillard),
                (i_fc,     i_drop, p_fc,     p_drop, self._eor_traj_dev_dot, self._eor_traj_dev_val, self._tr_traj_dev),
            ]

            neutral = f"color: {_BORDER}; font-size: 10px; {_FONT}"
            worst: tuple[float, str, float] | None = None  # (abs_dev, phase_name, signed_dev)
            any_ok = False
            dbg: list[str] = []  # per-phase trace for log-based testing

            for ia, ib, pa, pb, dot, val, name in phases:
                # indices 1–7 use 0 as the "unmarked" sentinel (mirror _abs convention)
                if not (ia is not None and ib is not None and 0 < ia < ib < n and pb > pa):
                    dot.setStyleSheet(neutral); val.setText("--")
                    dbg.append(f"{name}=skip(idx ia={ia} ib={ib} plan={pa:.2f}->{pb:.2f})")
                    continue
                t_a = float(tx[ia]); t_b = float(tx[ib])
                span = t_b - t_a
                if span <= 0:
                    dot.setStyleSheet(neutral); val.setText("--")
                    dbg.append(f"{name}=skip(span<=0)")
                    continue
                total = 0.0; count = 0
                for i in range(ia, ib + 1):
                    bt = temp2[i]
                    if bt is None or bt <= 0:
                        continue
                    u = (float(tx[i]) - t_a) / span          # progress 0..1 within phase
                    plan_bt = _interp_sorted(pa + u * (pb - pa), pc_t, pc_bt)
                    if plan_bt is None:
                        continue
                    total += float(bt) - plan_bt
                    count += 1
                if count == 0:
                    dot.setStyleSheet(neutral); val.setText("--")
                    dbg.append(f"{name}=skip(no samples)")
                    continue
                signed = total / count
                adev = abs(signed)
                if adev <= tol_ok:
                    color = _OK; verdict = self._tr_traj_inplan; tier = "ok"
                else:
                    color = _WARN if adev <= tol_warn else _CRIT
                    verdict = self._tr_traj_hotter if signed > 0 else self._tr_traj_cooler
                    tier = "warn" if adev <= tol_warn else "crit"
                dot.setStyleSheet(f"color: {color}; font-size: 10px; {_FONT}")
                val.setText(f"{signed:+.0f}°  {verdict}")
                any_ok = True
                if worst is None or adev > worst[0]:
                    worst = (adev, name, signed)
                dbg.append(
                    f"{name}: real {t_a:.0f}->{t_b:.0f}s ({span:.0f}s) "
                    f"plan {pa:.2f}->{pb:.2f}min n={count} dev={signed:+.1f}° [{tier}]")

            if not any_ok:
                _logd.debug("plan adherence: hidden (no usable phase) | " + " | ".join(dbg))
                box.hide(); return

            if worst is None or worst[0] <= tol_ok:
                self._eor_traj_verdict.setText(self._tr_traj_good)
            elif worst[0] <= tol_warn:
                self._eor_traj_verdict.setText(self._tpl_traj_slight.format(worst[1]))
            else:
                dirw = self._tr_traj_hotter if worst[2] > 0 else self._tr_traj_cooler
                self._eor_traj_verdict.setText(self._tpl_traj_off.format(worst[1], dirw))
            _logd.debug(
                "plan adherence: worst=%s | %s",
                (f"{worst[1]} {worst[2]:+.1f}°" if worst else "none"),
                " | ".join(dbg))
            box.show()
        except Exception:  # pylint: disable=broad-except
            try:
                box.hide()
            except Exception:  # pylint: disable=broad-except
                pass

# ══════════════════════════════════════════════════════════════════════════════
# Barre de configuration (grain + Agtron + bouton start/stop)
# ══════════════════════════════════════════════════════════════════════════════

class _SetupBar(QFrame):
    """Barre en haut du panel : sélection grain (ligne 1) + cible Agtron + bouton (ligne 2)."""

    # Style QComboBox partagé — clé : la popup hérite du même fond sombre
    _COMBO_STYLE = f"""
        QComboBox {{
            background: {_BG};
            border: 1px solid {_BORDER};
            border-radius: 5px;
            padding: 5px 8px;
            color: {_TEXT};
            font-size: 12px;
            {_FONT}
        }}
        QComboBox:hover {{
            border: 1px solid {_ACCENT};
        }}
        QComboBox:disabled {{
            color: #45475A;
            background: {_SURFACE};
            border-color: #2A2A3A;
        }}
        QComboBox::drop-down {{
            border: none;
            width: 20px;
        }}
        QComboBox::down-arrow {{
            image: none;
            border-left: 4px solid transparent;
            border-right: 4px solid transparent;
            border-top: 5px solid {_ACCENT};
            margin-right: 6px;
        }}
        /* ── Popup / liste déroulante ── */
        QComboBox QAbstractItemView {{
            background: #1E1E2E;
            color: {_TEXT};
            border: 1px solid {_ACCENT};
            border-radius: 4px;
            selection-background-color: {_ACCENT};
            selection-color: #11111B;
            outline: none;
            padding: 2px;
        }}
        QComboBox QAbstractItemView::item {{
            min-height: 28px;
            padding-left: 10px;
            color: {_TEXT};
            background: transparent;
        }}
        QComboBox QAbstractItemView::item:hover {{
            background: #313244;
            color: white;
        }}
        QComboBox QAbstractItemView::item:selected {{
            background: {_ACCENT};
            color: #11111B;
            font-weight: bold;
        }}
        /* Scrollbar dans la popup */
        QComboBox QAbstractScrollArea QScrollBar:vertical {{
            background: #181825;
            width: 8px;
            border-radius: 4px;
        }}
        QComboBox QAbstractScrollArea QScrollBar::handle:vertical {{
            background: {_BORDER};
            border-radius: 4px;
            min-height: 20px;
        }}
        /* Keep the dark tooltip style even when embedded in anchored mode */
        QToolTip {{
            background-color: #2D2F3F;
            color: white;
            border: 1px solid #585B70;
            padding: 5px;
            border-radius: 3px;
            font-size: 11px;
        }}
    """

    def __init__(self):
        super().__init__()
        self.setStyleSheet(f"""
            QFrame {{
                background: {_SURFACE};
                border-bottom: 1px solid {_BORDER};
                border-radius: 0px;
            }}
            QLabel {{
                border: none;
                background: transparent;
                color: #94A3B8;
                font-size: 10px;
                font-weight: 800;
                letter-spacing: 0.5px;
                {_FONT}
            }}
        """)

        # Layout vertical : 2 lignes
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(8)

        # ── Ligne 1 : Grain ──────────────────────────────────────────────────
        row1 = QVBoxLayout()
        row1.setSpacing(4)
        # Header row: GREEN BEAN label + anchor/float toggle (Guided level only).
        # The anchor control lives here so the main header band stays clean.
        bean_hdr = QHBoxLayout()
        bean_hdr.setContentsMargins(0, 0, 0, 0)
        bean_hdr.setSpacing(6)
        self._lbl_bean = QLabel(QApplication.translate("tilauscope_roast_assistant", "Green Bean").upper())
        self.btn_anchor = QPushButton("⤢")
        self.btn_anchor.setFixedSize(34, 28)
        self.btn_anchor.setToolTip(QApplication.translate(
            "tilauscope_roast_assistant", "Anchor / float the assistant panel"))
        # Explicit QToolTip rule so the tooltip keeps its dark style even when
        # the body is embedded in the anchored host (no inherited app style).
        self.btn_anchor.setStyleSheet(f"""
            QPushButton {{ background: #181825; color: #94A3B8;
                border: 1px solid {_BORDER}; border-radius: 5px;
                font-size: 16px; font-weight: bold; }}
            QPushButton:hover {{ background: #1E1E2E; color: {_ACCENT};
                border-color: {_ACCENT}; }}
            QToolTip {{ background-color: #2D2F3F; color: white;
                border: 1px solid #585B70; padding: 5px;
                border-radius: 3px; font-size: 11px; }}
        """)
        self.btn_anchor.hide()
        bean_hdr.addWidget(self._lbl_bean)
        bean_hdr.addStretch(1)
        bean_hdr.addWidget(self.btn_anchor)
        self.combo_bean = QComboBox()
        self.combo_bean.setView(QListView())
        self.combo_bean.setItemDelegate(QStyledItemDelegate())
        self.combo_bean.setStyleSheet(self._COMBO_STYLE)
        self.combo_bean.setToolTip(QApplication.translate("tilauscope_roast_assistant","Green bean selected for this assistant"))
        self.combo_bean.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.combo_bean.setMinimumHeight(32)
        row1.addLayout(bean_hdr)
        row1.addWidget(self.combo_bean)

        # ── Ligne 2 : Cible Agtron ───────────────────────────────────────────
        row2 = QVBoxLayout()
        row2.setSpacing(4)

        self._lbl_agtron = QLabel(QApplication.translate("tilauscope_roast_assistant","ROASTING TARGET"))
        self.combo_agtron = QComboBox()
        self.combo_agtron.setView(QListView())
        self.combo_agtron.setItemDelegate(QStyledItemDelegate())
        self.combo_agtron.setStyleSheet(self._COMBO_STYLE)
        self.combo_agtron.setToolTip(QApplication.translate("tilauscope_roast_assistant","Target roasting level (Agtron scale)"))
        self.combo_agtron.setMinimumHeight(32)
        for a in _AGTRON_CHOICES:
            self.combo_agtron.addItem(f"{a.name}  –  {a.description}", userData=a)
        for i in range(self.combo_agtron.count()):
            if self.combo_agtron.itemText(i).startswith("Medium "):
                self.combo_agtron.setCurrentIndex(i)
                break
        row2.addWidget(self._lbl_agtron)
        row2.addWidget(self.combo_agtron)

        outer.addLayout(row1)
        outer.addLayout(row2)

    def set_active(self, active: bool) -> None:
        self.combo_bean.setEnabled(not active)
        self.combo_agtron.setEnabled(not active)

    def show_combos(self, visible: bool) -> None:
        """Show or hide both combo boxes and their labels (hidden during roast)."""
        self._lbl_bean.setVisible(visible)
        self.combo_bean.setVisible(visible)
        self._lbl_agtron.setVisible(visible)
        self.combo_agtron.setVisible(visible)
        self.setVisible(visible)

    def populate_beans(self, beans: list[GreenBean], current_uuid: str|None = None, agtron_color:int|None = None) -> None:
        self.combo_bean.blockSignals(True)
        self.combo_bean.clear()
        select_idx = 0
        for i, b in enumerate(beans):
            label = f"{b.name}"
            if b.process:
                label += f" · {b.process}"
            if b.crop:
                label += f" {b.crop}"
            ## TILAU ## a bean only listed because it is the one being roasted
            ## (bottom of the bag) is flagged so the operator is not surprised.
            if (getattr(b, "weight_left", 0.0) or 0.0) <= 0:
                label += QApplication.translate("tilauscope_roast_assistant", " (empty stock)")
            self.combo_bean.addItem(label, userData=b)
            if current_uuid and b.uuid == current_uuid:
                select_idx = i
        if self.combo_bean.count() > 0:
            self.combo_bean.setCurrentIndex(select_idx)
        self.combo_bean.blockSignals(False)
        if agtron_color is not None and agtron_color > 0:
            for i in range(self.combo_agtron.count()):
                scale = self.combo_agtron.itemData(i)
                if scale and scale.agtron_range.min_value <= agtron_color <= scale.agtron_range.max_value:
                    self.combo_agtron.setCurrentIndex(i)
                    _logd.debug(f"RoastAssistant: auto-selected Agtron target {scale.name} for color {agtron_color}")
                    break

    def selected_bean(self) -> GreenBean|None:
        return self.combo_bean.currentData()

    def selected_agtron(self) -> AgtronScale|None:
        return self.combo_agtron.currentData()

# ══════════════════════════════════════════════════════════════════════════════
# En-tête Grain actif
# ══════════════════════════════════════════════════════════════════════════════

class _BeanHeader(QFrame):
    """Bande affichant le résumé du grain actif et la cible de torréfaction."""

    def __init__(self):
        super().__init__()
        self.setStyleSheet(f"""
            QFrame {{
                background: #16161E;
                border-bottom: 1px solid {_BORDER};
            }}
            QLabel {{ border: none; background: transparent; {_FONT} }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(3)

        # Name row: bean name label + start/stop button on the right
        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        self._lbl_name = QLabel("--")
        self._lbl_name.setStyleSheet(
            f"color: {_ACCENT}; font-size: 14px; font-weight: 900;"
        )
        # Batch identity badge (filled from qmc at DROP; empty/hidden until assigned)
        self._lbl_batch = QLabel("")
        self._lbl_batch.setStyleSheet(
            f"color: {_OK}; font-size: 12px; font-weight: bold; "
            f"font-family: 'JetBrains Mono';"
        )
        self._lbl_batch.hide()
        # ── Start/Stop button (moved here from SetupBar) ─────────────────────
        self.btn_toggle = QPushButton("▶")
        self.btn_toggle.setFixedSize(44, 32)
        self.btn_toggle.setCheckable(True)
        self.btn_toggle.setToolTip(QApplication.translate("tilauscope_roast_assistant","Start / Stop assistant"))
        self._set_btn_style(False)

        ## TILAU ## AutoPilot chip-button (AutoRoast-Spec §5) — left of ▶/⏸, the
        ## only band visible in BOTH anchored and floating modes. The chip IS the
        ## button: state (off/armed/paused/blocked) + arming action in one control.
        self.btn_auto = QPushButton("AUTO")
        self.btn_auto.setFixedHeight(32)
        self.btn_auto.setMinimumWidth(66)
        self.btn_auto.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_auto.setToolTip(QApplication.translate(
            "tilauscope_roast_assistant", "Auto mode: the roast plan drives the levers. Tap to arm / disarm."))
        self.set_auto_state("off")

        name_row.addWidget(self._lbl_batch)
        name_row.addWidget(self._lbl_name, 1)
        name_row.addWidget(self.btn_auto)
        name_row.addWidget(self.btn_toggle)

        self._lbl_details = QLabel("")
        self._lbl_details.setStyleSheet(
            f"color: #94A3B8; font-size: 11px;"
        )
        self._lbl_details.setWordWrap(True)

        layout.addLayout(name_row)
        layout.addWidget(self._lbl_details)

    def _set_btn_style(self, active: bool) -> None:
        color = _OK if active else "#494C91"
        self.btn_toggle.setStyleSheet(f"""
            QPushButton {{
                background: #181825; color: {color};
                border: 2px solid {color}; border-radius: 6px;
                font-size: 14px; font-weight: bold;
            }}
            QPushButton:hover {{ background: #1E1E2E; }}
            QPushButton:pressed {{ background: {color}; color: #11111B; }}
            QToolTip {{ background-color: #2D2F3F; color: white;
                border: 1px solid #585B70; padding: 5px;
                border-radius: 3px; font-size: 11px; }}
        """)
        self.btn_toggle.setText("■" if active else "▶")

    def set_active(self, active: bool) -> None:
        self._set_btn_style(active)

    ## TILAU ## AutoPilot chip states — colors mirror the validated mockup:
    ## off = dim, armed = green, paused = amber, blocked = extinguished.
    _AUTO_STYLES = {
        "off":     ("AUTO",    "#585B70", "#6C7086", "transparent"),
        "armed":   ("● AUTO",  "#A6E3A1", "#A6E3A1", "rgba(166,227,161,0.10)"),
        "paused":  ("⏸ AUTO",  "#F9E2AF", "#F9E2AF", "rgba(249,226,175,0.10)"),
        "blocked": ("AUTO",    "#313244", "#45475A", "transparent"),
    }

    def set_auto_state(self, state: str) -> None:  ## TILAU ##
        text, border, color, bg = self._AUTO_STYLES.get(state, self._AUTO_STYLES["off"])
        self.btn_auto.setText(text)
        self.btn_auto.setStyleSheet(f"""
            QPushButton {{
                background: {bg}; color: {color};
                border: 1.5px solid {border}; border-radius: 14px;
                font-size: 10.5px; font-weight: 800; letter-spacing: 1px;
                padding: 0 10px; font-family: 'JetBrains Mono';
            }}
            QPushButton:hover {{ background: #1E1E2E; }}
            QToolTip {{ background-color: #2D2F3F; color: white;
                border: 1px solid #585B70; padding: 5px;
                border-radius: 3px; font-size: 11px; }}
        """)

    def set_start_stop_visible(self, visible: bool) -> None:  ## TILAU ##
        """Show or hide the start/stop button (hidden in Guided mode). ## TILAU ##"""
        self.btn_toggle.setVisible(visible)

    def update_batch(self, prefix: str, nr: int, pos: int | None = None) -> None:
        """Show the assigned batch identity; hidden while unassigned (nr<=0)."""
        label = format_batch_label(prefix, nr, pos)
        self._lbl_batch.setText(label)
        self._lbl_batch.setVisible(bool(label))

    def update_bean(self, bean: GreenBean|None,
                    agtron: AgtronScale|None) -> None:
        if bean is None:
            self._lbl_name.setText(QApplication.translate("tilauscope_roast_assistant","No green been has been selected"))
            self._lbl_details.setText("")
            return
        self._lbl_name.setText(bean.name)
        # Ligne 1 : process + densité + altitude
        line1_parts = []
        if bean.process:
            line1_parts.append(bean.process)
        if bean.density:
            line1_parts.append(f"ρ {bean.density:.0f} g/l")
        if bean.altitude:
            line1_parts.append(f"{bean.altitude} m")
        # Ligne 2 : humidité + cible Agtron
        line2_parts = []
        if bean.last_humidity:
            line2_parts.append(QApplication.translate("Label","Humidity")+f" {bean.last_humidity:.1f}%")
        if agtron:
            line2_parts.append(f"▶ "+QApplication.translate("Label","target")+f"  {agtron.name}  ({agtron.description})")
        lines = []
        if line1_parts:
            lines.append("  ·  ".join(line1_parts))
        if line2_parts:
            lines.append("  ·  ".join(line2_parts))
        self._lbl_details.setText("\n".join(lines))

class _TapFrame(QFrame):
    """## TILAU ## QFrame cliquable — les tuiles leviers du cockpit : un tap =
    reprise en main (pause AUTO). Nécessaire car en mode ancré Guided les
    sliders Artisan ne sont pas visibles et le cockpit masque les quick-adjust :
    sans ce geste, aucun moyen de reprendre la main depuis le panneau."""
    tapped = pyqtSignal()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.tapped.emit()
        super().mousePressEvent(event)


class _AutoCockpitPage(QWidget):
    """## TILAU ## Vue COCKPIT du mode AUTO (maquette v6 validée le 2026-07-09).

    Quatre éléments, gros, ZÉRO texte d'appoint — la machine pilote, elle ne se
    justifie pas à l'écran (le détail vit dans les événements Artisan et le log) :
      1. bandeau « ● AUTO PILOTE · phase · chrono »
      2. UN état en toutes lettres (ON PLAN ✓ / DRIFTING ↑↓ / PAUSED)
      3. UNE carte action (quoi + quand)
      4. quatre tuiles leviers (nom + valeur, flash quand AUTO agit) + barre jalon
    Remplace la page de phase quand AUTO est armé ou en pause."""

    lever_tapped = pyqtSignal()   ## TILAU ## un tap sur une tuile = reprise en main

    _TILE_ORDER: Final = (3, 0, 1, 2)   # BURNER, AIR, DRUM, EXT
    _TILE_COLORS: Final = {3: "#F38BA8", 0: "#89B4FA", 1: "#CBA6F7", 2: "#94E2D5"}
    ## TILAU ## fonds de flash en rgba() : un hex 8 chiffres est lu #AARRGGBB par
    ## Qt (alpha en PREMIER) — "#F38BA8"+"22" devenait un vert olive opaque.
    _TILE_RGBA: Final = {3: "rgba(243,139,168,0.14)", 0: "rgba(137,180,250,0.14)",
                         1: "rgba(203,166,247,0.14)", 2: "rgba(148,226,213,0.14)"}

    def __init__(self, aw: "ApplicationWindow"):
        super().__init__()
        self.aw = aw
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 4)
        lay.setSpacing(10)

        # 1. bandeau AUTO PILOTE
        self._bar = QFrame()
        self._bar_lay = QHBoxLayout(self._bar)
        self._bar_lay.setContentsMargins(14, 10, 14, 10)
        self._lbl_pilot = QLabel("● AUTO")
        self._lbl_phase = QLabel("")
        self._bar_lay.addWidget(self._lbl_pilot)
        self._bar_lay.addWidget(self._lbl_phase)
        self._bar_lay.addStretch()
        self._bar_armed: "bool | None" = None
        self._apply_bar_style(True)

        # 2. état en toutes lettres
        self._lbl_status = QLabel("--")
        self._lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_color: "str | None" = None

        # 3. carte action
        self._card = QFrame()
        self._card.setStyleSheet(
            f"QFrame {{ background: {_SURFACE}; border: 1.5px solid #89B4FA; "
            f"border-radius: 10px; }} QLabel {{ border: none; background: transparent; }}")
        _cl = QVBoxLayout(self._card)
        _cl.setContentsMargins(14, 12, 14, 12)
        _cl.setSpacing(2)
        self._lbl_action = QLabel("--")
        self._lbl_action.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_action.setWordWrap(True)
        self._lbl_action.setStyleSheet(
            f"color: #CDD6F4; font-size: 19px; font-weight: 800; {_FONT}")
        self._lbl_when = QLabel("")
        self._lbl_when.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_when.setStyleSheet(f"color: #9399B2; font-size: 12px; {_FONT}")
        _cl.addWidget(self._lbl_action)
        _cl.addWidget(self._lbl_when)

        # 4. tuiles leviers
        tiles_row = QHBoxLayout()
        tiles_row.setSpacing(8)
        self._tiles: dict[int, tuple[QFrame, QLabel]] = {}
        self._tile_flash: dict[int, bool] = {}
        for idx in self._TILE_ORDER:
            fr = _TapFrame()
            fr.tapped.connect(self.lever_tapped)
            fr.setCursor(Qt.CursorShape.PointingHandCursor)
            fr.setToolTip(QApplication.translate(
                "tilauscope_roast_assistant", "Tap to take over this roast (pauses AUTO)"))
            tl = QVBoxLayout(fr)
            tl.setContentsMargins(4, 10, 4, 10)
            tl.setSpacing(2)
            try:
                name = str(aw.qmc.etypes[idx]).upper()
            except (AttributeError, IndexError):
                name = f"SLD{idx}"
            n = QLabel(name)
            n.setAlignment(Qt.AlignmentFlag.AlignCenter)
            n.setStyleSheet(f"color: #9399B2; font-size: 10px; font-weight: 800; "
                            f"{_FONT} letter-spacing: 1px; border:none; background:transparent;")
            v = QLabel("--")
            v.setAlignment(Qt.AlignmentFlag.AlignCenter)
            v.setStyleSheet(f"color: {self._TILE_COLORS[idx]}; font-size: 24px; "
                            f"font-weight: 900; {_FONT} border:none; background:transparent;")
            tl.addWidget(n)
            tl.addWidget(v)
            self._tiles[idx] = (fr, v)
            self._tile_flash[idx] = True   # force le 1er style
            self._set_tile_flash(idx, False)
            tiles_row.addWidget(fr, 1)

        # barre jalon
        ms_row = QHBoxLayout()
        ms_row.setSpacing(10)
        self._lbl_ms = QLabel("")
        self._lbl_ms.setStyleSheet(f"color: #9399B2; font-size: 12px; font-weight: 800; {_FONT} border:none;")
        self._ms_outer = QFrame()
        self._ms_outer.setFixedHeight(6)
        self._ms_outer.setStyleSheet(f"background: {_BORDER}; border-radius: 3px;")
        self._ms_inner = QFrame(self._ms_outer)
        self._ms_inner.setFixedHeight(6)
        self._ms_inner.setStyleSheet("background: #F9E2AF; border-radius: 3px;")
        self._lbl_ms_r = QLabel("")
        self._lbl_ms_r.setStyleSheet(f"color: #9399B2; font-size: 12px; {_FONT} border:none;")
        ms_row.addWidget(self._lbl_ms)
        ms_row.addWidget(self._ms_outer, 1)
        ms_row.addWidget(self._lbl_ms_r)

        ## TILAU ## bouton de jalon : en cockpit les pages détaillées (et leurs
        ## boutons DE/FC/DROP) sont masquées — sans lui, aucun marquage possible
        ## depuis le panneau (retour Tilau : FC/DROP impossibles en cockpit).
        ## Un seul bouton, contextualisé par phase ; devient « Annuler » pendant
        ## le compte à rebours d'auto-DROP.
        self.btn_ms = _ContextButton("--", "", style='dim')

        lay.addWidget(self._bar)
        _inner = QVBoxLayout()
        _inner.setContentsMargins(12, 0, 12, 0)
        _inner.setSpacing(10)
        _inner.addWidget(self._lbl_status)
        _inner.addWidget(self._card)
        _inner.addLayout(tiles_row)
        _inner.addLayout(ms_row)
        _inner.addWidget(self.btn_ms)
        lay.addLayout(_inner)
        lay.addStretch(1)

    def _apply_bar_style(self, armed: bool) -> None:
        if armed == self._bar_armed:
            return
        self._bar_armed = armed
        c, bg, bd = (("#A6E3A1", "rgba(166,227,161,0.07)", "rgba(166,227,161,0.35)") if armed
                     else ("#F9E2AF", "rgba(249,226,175,0.07)", "rgba(249,226,175,0.35)"))
        self._bar.setStyleSheet(
            f"QFrame {{ background: {bg}; border: none; border-bottom: 1px solid {bd}; }}"
            f"QLabel {{ border: none; background: transparent; }}")
        self._lbl_pilot.setStyleSheet(
            f"color: {c}; font-size: 14px; font-weight: 900; letter-spacing: 1.5px; {_FONT}")
        self._lbl_phase.setStyleSheet(f"color: #9399B2; font-size: 12px; {_FONT}")

    def _set_tile_flash(self, idx: int, on: bool) -> None:
        if on == self._tile_flash.get(idx):
            return
        self._tile_flash[idx] = on
        c = self._TILE_COLORS[idx]
        if on:
            self._tiles[idx][0].setStyleSheet(
                f"QFrame {{ background: {self._TILE_RGBA[idx]}; "
                f"border: 1.5px solid {c}; border-radius: 9px; }}")
        else:
            self._tiles[idx][0].setStyleSheet(
                f"QFrame {{ background: {_SURFACE}; border: 1px solid {_BORDER}; border-radius: 9px; }}")

    def refresh(self, armed: bool, pilot_txt: str, phase_txt: str,
                status: str, status_color: str,
                action: str, when: str,
                levers: "dict[int, float | None]", flashed: "set[int]",
                ms_label: str, ms_pct: float, ms_right: str) -> None:
        self._apply_bar_style(armed)
        if self._lbl_pilot.text() != pilot_txt:
            self._lbl_pilot.setText(pilot_txt)
        if self._lbl_phase.text() != phase_txt:
            self._lbl_phase.setText(phase_txt)
        if status_color != self._status_color:
            self._status_color = status_color
            self._lbl_status.setStyleSheet(
                f"color: {status_color}; font-size: 26px; font-weight: 900; "
                f"letter-spacing: 1px; {_FONT} border: none;")
        if self._lbl_status.text() != status:
            self._lbl_status.setText(status)
        if self._lbl_action.text() != action:
            self._lbl_action.setText(action)
        if self._lbl_when.text() != when:
            self._lbl_when.setText(when)
        for idx, (_fr, vlbl) in self._tiles.items():
            v = levers.get(idx)
            txt = f"{v:.0f}" if v is not None else "--"
            if vlbl.text() != txt:
                vlbl.setText(txt)
            self._set_tile_flash(idx, idx in flashed)
        if self._lbl_ms.text() != ms_label:
            self._lbl_ms.setText(ms_label)
        if self._lbl_ms_r.text() != ms_right:
            self._lbl_ms_r.setText(ms_right)
        w = self._ms_outer.width()
        if w > 0:
            self._ms_inner.setFixedWidth(max(4, int(w * max(0.0, min(100.0, ms_pct)) / 100.0)))


# ══════════════════════════════════════════════════════════════════════════════
# Widget principal — RoastAssistantPanel
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(slots=True)
class OmnifluxBinding:
    """Holds resolved indices into Artisan's extraXXX arrays for the Omniflux."""
    color_device_idx: int = -1      # index in extradevices for MODBUS34
    roc_device_idx:   int = -1      # index in extradevices for MODBUS56
    valid: bool = False

class AccessOmniflux():
    _COLOR_SMOOTH_N = 5   # average over last 5 samples (~5 s at 1 Hz)

    def __init__(self, aw:ApplicationWindow):
        self.aw = aw
        self.omniflux = self.detect_omniflux_devices(aw)
        self._color_hist: list[float] = []
        self._roc_hist:   list[float] = []
       

    def _get_omniflux_live(self) -> tuple[float, float]:
        ci = self.omniflux.color_device_idx
        try:
            color_series = self.aw.qmc.extratemp1[ci][-1] if self.aw.qmc.flagstart else self.aw.qmc.RTextratemp1[ci]
            raw_agtron = color_series if color_series else -1.0
        except (IndexError, TypeError):
            raw_agtron = -1.0
        try:
            roc_series = self.aw.qmc.extratemp2[ci][-1] if self.aw.qmc.flagstart else self.aw.qmc.RTextratemp2[ci]
            raw_roc = roc_series if roc_series else -1.0
        except (IndexError, TypeError):
            raw_roc = -1.0

        if raw_agtron > 0:
            self._color_hist.append(raw_agtron)
            if len(self._color_hist) > self._COLOR_SMOOTH_N:
                self._color_hist.pop(0)
        if raw_roc != -1.0:
            self._roc_hist.append(raw_roc)
            if len(self._roc_hist) > self._COLOR_SMOOTH_N:
                self._roc_hist.pop(0)

        agtron = sum(self._color_hist) / len(self._color_hist) if self._color_hist else -1.0
        roc    = sum(self._roc_hist)   / len(self._roc_hist)   if self._roc_hist  else -1.0
        return agtron, roc
    
    def detect_omniflux_devices(self,aw: ApplicationWindow)-> OmnifluxBinding:
        """
        Scan Artisan extra-devices to locate the Omniflux Agtron/RoC channels.
        Must be called after charge (qmc data is available) or on settings load.
        """
        binding = OmnifluxBinding()
        qmc = aw.qmc
        modbus = getattr(aw, 'modbus', None)

        if modbus is None:
            _logd.warning("omniflux detect: no modbus object found")
            return binding

        # Verify RTU serial mode is engaged
        if getattr(modbus, 'type', '') != 0 or not getattr(modbus, 'comport', None):
            _logd.warning("omniflux detect: modbus not in serial RTU mode or comport not detected")
            return binding

        # verify channels and register settings which are expected on MODBUS34
        match = (
            modbus.inputDeviceIds[0], modbus.inputDeviceIds[1],
            modbus.inputDeviceIds[2], modbus.inputDeviceIds[3],
            modbus.inputDeviceIds[4], modbus.inputDeviceIds[5],
            modbus.inputRegisters[0], modbus.inputRegisters[1],
            modbus.inputRegisters[2], modbus.inputRegisters[3],
            modbus.inputRegisters[4], modbus.inputRegisters[5],
            modbus.inputCodes[2], modbus.inputCodes[3],
            modbus.inputModes[2], modbus.inputModes[3],
            modbus.inputDivs[2], modbus.inputDivs[3]
        ) == (1, 1, 2, 2, 3, 3, 10, 11, 12, 13, 14, 15, 3, 3, 'C', 'C', 1, 1)

        if not match:
            return binding

        n = len(qmc.extradevices)
        for i in range(n):
            n1 = qmc.extraname1[i].strip().upper() if i < len(qmc.extraname1) else ""
            n2 = qmc.extraname2[i].strip().upper() if i < len(qmc.extraname2) else ""

            # Color device: name has "AGTRON", registers 12+13
            if "AGTRON" in n1 and "ROC" in n2:
                binding.color_device_idx = i
                binding.roc_device_idx = i+1
                _logd.debug(f"omniflux detect: color device found at extra index {i}")
                break

        binding.valid = binding.color_device_idx >= 0
        if not binding.valid:
            _logd.warning("omniflux detect: color device not found — color PID layer disabled")
        return binding

class RoastAssistantPanel(QWidget):
    """
    Fenêtre flottante d'assistance contextuelle à la torréfaction.

    Paramètres
    ----------
    aw     : ApplicationWindow d'Artisan
    parent : TilauScope (fenêtre parente)
    """

    # Phases internes
    _PHASE_IDLE    = 0
    _PHASE_DRY     = 1
    _PHASE_MAI     = 2
    _PHASE_DEV     = 3
    _PHASE_PREHEAT = 4
    _PHASE_DROP    = 5

    _PHASE_MAP  = {"DRY": _PHASE_DRY, "MAI": _PHASE_MAI, "DEV": _PHASE_DEV, "COOL": _PHASE_DROP, "PREHEAT": _PHASE_PREHEAT, "DROP": _PHASE_DROP}
    _PAGE_COCKPIT = 6   ## TILAU ## vue AUTO (maquette v6) — remplace la page de phase quand AUTO pilote

    # Emitted when the user closes the panel via the floating ✕, so the host
    # can re-sync its open/close button state. ## TILAU ##
    closed = pyqtSignal()
    # Emitted when the user toggles anchor/float from the panel-side control
    # (Guided level), so the host can run its anchor logic. ## TILAU ##
    anchor_requested = pyqtSignal()

    def __init__(self, aw: "ApplicationWindow", parent: QWidget):
        super().__init__(parent)
        self.aw       = aw
        self._parent  = parent
        self.is_active: bool = False
        self._operator_level: str = "guided"  ## TILAU ##

        # Drapeaux internes
        self._current_phase: int = self._PHASE_IDLE
        self._bean: GreenBean|None = None
        self._agtron: AgtronScale|None = None
        self._plan: dict|None = None  # dict retourné par generate_roast_plan()
        # Générateur de plan de la session — conservé entre les régénérations
        # pour que son cache d'analyse historique (indépendant de l'ambiant)
        # évite de relire tous les .alog sur le thread UI à chaque régen.
        self._rp: "TilauScopeRoastPlan | None" = None
        self._bt_at_fcs: float = 0.0

        # ── Plan vivant (recalage aux jalons) ──────────────────────────────  ## TILAU ##
        # _plan est le plan VIVANT (re-ancré à chaque jalon réel TP/DRYe/FCs) ;
        # _plan_initial reste figé au démarrage — c'est la référence honnête du
        # bilan EOR (sinon l'adhérence serait trivialement bonne par construction).
        self._plan_initial: dict|None = None
        self._replans_applied: list[tuple[str, float, float]] = []   # (milestone, t_min, bt_native)
        self._replan_attempted: set[str] = set()                     # one-shot guard (O(1) hot path)
        self._replan_notice: "tuple[str, str, float] | None" = None  # (texte, niveau, expiration monotonic)
        self._soak_note: "str | None" = None   # ligne heat-soak affichée en preheat (cache)
        # #10 : bandeau « jalon détecté — confirmer ? » (bip one-shot par suggestion)
        self._last_milestone_beep_t: "float | None" = None
        self._tr_confirm_de = QApplication.translate(
            "tilauscope_roast_assistant", "👂 DRY END detected — tap to confirm")
        self._tr_confirm_fc = QApplication.translate(
            "tilauscope_roast_assistant", "👂 FC detected — tap to confirm")
        self._relaunch_requested: bool = False  # relance back-to-back : forcer le redémarrage assistant

        # ── Fenêtre d'inertie burner (coach quantifié) ─────────────────────  ## TILAU ##
        # Tout mouvement du slider burner (opérateur ou alarme de rampe) ouvre
        # une fenêtre pendant laquelle le conseil RoR directionnel est suspendu
        # (aw._tilau_burner_watch, lu par _ror_deviation_advice). Le lag est
        # dérivé de la réactivité thermique de la machine.
        self._burner_last_pct: "int | None" = None

        ## TILAU ## AutoPilot v1a (feedforward — AutoRoast-Spec §3 étage 1, §5) ──
        ## 'off' | 'armed' | 'paused' ; armement = consentement, opt-in par session.
        self._ap_state: str = "off"
        self._ap_expected: dict[int, float] = {}      # idx slider → valeur posée par l'AutoPilot
        self._ap_slider_last: dict[int, float] = {}   # dernière valeur observée (détection reprise en main)
        self._ap_notice: "tuple[str, str, float] | None" = None  # (texte, niveau, expiration monotonic)
        self._ap_bt_prev: "float | None" = None   # BT du tick précédent (franchissement montant de rampe)
        self._ap_charge_settle_until: float = 0.0  # seam CHARGE : fenêtre de grâce anti-pause (handoff PID préchauffe→roast)
        self._tr_ap_blocked_lowconf = QApplication.translate(
            "tilauscope_roast_assistant", "AUTO unavailable — plan confidence is too low for this roast")
        self._tr_ap_blocked_noplan = QApplication.translate(
            "tilauscope_roast_assistant", "AUTO unavailable — no roast plan for this session")
        self._tr_ap_armed_note = QApplication.translate(
            "tilauscope_roast_assistant", "⚙ AUTO armed — the plan drives the levers at each phase")
        self._tr_ap_paused_note = QApplication.translate(
            "tilauscope_roast_assistant", "⏸ AUTO paused — manual input detected. Tap AUTO to resume.")
        self._tr_ap_off_note = QApplication.translate(
            "tilauscope_roast_assistant", "AUTO off — you have full control")
        self._tpl_ap_phase = QApplication.translate("tilauscope_roast_assistant", "⚙ AUTO · {0} → {1}")
        self._tpl_ap_ramp = QApplication.translate("tilauscope_roast_assistant", "⚙ AUTO · Burner → {0}% (ramp at {1}°)")
        self._tpl_ap_cool = QApplication.translate(
            "tilauscope_roast_assistant", "⚙ AUTO · DROP → cooling ({0}) — AUTO done, you have full control")
        ## TILAU ## vue cockpit (v6) — dernière action + flashes tuiles + textes
        self._ap_last_action: "tuple[str, float] | None" = None   # (texte, t_mono)
        self._ap_lever_flash: dict[int, float] = {}               # idx → t_mono de la pose
        self._ap_automark_done: set[str] = set()                  # "DE"/"FC" one-shot
        self._tr_cp_pilot   = QApplication.translate("tilauscope_roast_assistant", "● AUTO PILOTING")
        self._tr_cp_paused  = QApplication.translate("tilauscope_roast_assistant", "⏸ AUTO PAUSED")
        self._tr_cp_onplan  = QApplication.translate("tilauscope_roast_assistant", "ON PLAN ✓")
        self._tr_cp_drift_h = QApplication.translate("tilauscope_roast_assistant", "DRIFTING ↑")
        self._tr_cp_drift_l = QApplication.translate("tilauscope_roast_assistant", "DRIFTING ↓")
        self._tr_cp_follow  = QApplication.translate("tilauscope_roast_assistant", "FOLLOWING PLAN")
        self._tr_cp_pausest = QApplication.translate("tilauscope_roast_assistant", "PAUSED — tap AUTO")
        self._tr_cp_waiting = QApplication.translate("tilauscope_roast_assistant", "⚙ following the plan")
        self._tpl_cp_ago    = QApplication.translate("tilauscope_roast_assistant", "{0}s ago")
        self._tr_cp_justnow = QApplication.translate("tilauscope_roast_assistant", "just now")
        self._tpl_ap_marked = QApplication.translate("tilauscope_roast_assistant", "⚙ {0} marked (auto)")
        self._cp_phase_words = {
            self._PHASE_DRY: QApplication.translate("tilauscope_roast_assistant", "DRYING"),
            self._PHASE_MAI: QApplication.translate("tilauscope_roast_assistant", "MAILLARD"),
            self._PHASE_DEV: QApplication.translate("tilauscope_roast_assistant", "DEVELOPMENT"),
        }
        self._cp_ms_words = {
            self._PHASE_DRY: "DE", self._PHASE_MAI: "FC", self._PHASE_DEV: "DROP",
        }
        ## TILAU ## jalons en cockpit : bouton contextuel + auto-DROP plan (10 s annulables)
        self._ap_drop_deadline: "float | None" = None   # t_mono du tir auto-DROP
        self._ap_drop_cancelled: bool = False           # annulé = plus jamais re-armé (session)
        self._tr_cp_btn_de   = QApplication.translate("tilauscope_roast_assistant", "Mark DRY END")
        self._tr_cp_btn_fc   = QApplication.translate("tilauscope_roast_assistant", "Mark FC START")
        self._tr_cp_btn_drop = QApplication.translate("tilauscope_roast_assistant", "Mark DROP")
        self._tr_cp_btn_cancel = QApplication.translate("tilauscope_roast_assistant", "✕ Cancel auto-DROP")
        self._tpl_ap_dropin  = QApplication.translate("tilauscope_roast_assistant", "⬇ DROP in {0}s — plan target reached")
        self._tr_ap_dropmark = QApplication.translate("tilauscope_roast_assistant", "⚙ DROP marked (auto)")
        ## TILAU ## v1b — moteur de trim continu (autopilot_core, calé Sim-1/Sim-2)
        self._ap_core = AutoPilotCore(self._ap_trim_params())
        self._tpl_ap_trim = QApplication.translate("tilauscope_roast_assistant", "⚙ AUTO · {0} → {1}% ({2})")
        self._tpl_ap_dev_ramp = QApplication.translate("tilauscope_roast_assistant", "⚙ AUTO · DEV {0}")
        self._tr_ap_ceiling = QApplication.translate(
            "tilauscope_roast_assistant", "⚠ AUTO · trim at its ceiling — check the plan")
        ## TILAU ## v2 — « tenir le feu » en dev (rate-limiter exotherme), filet
        ## réactif minimal AIR-d'abord, et flag A/B feedforward-seul vs +trim.
        self._ap_ff_only: bool = False           # lu depuis QSettings à l'armement
        self._ap_dev_heater_pending: "float | None" = None  # cible feu en file (monotone)
        self._ap_dev_rate_anchor: "tuple[float, float] | None" = None  # (t_fc_sec, burner_pct)
        self._ap_net_offset: float = 0.0         # offset AIR posé par le filet (auto-résorbé)
        self._ap_net_last: float = 0.0           # monotonic de la dernière touche du filet
        self._ap_net_quiet_since: "float | None" = None  # début du calme post-crash
        self._drum_last_pct: "float | None" = None       # watch tambour (mute détection RoR)
        self._tpl_ap_devfire = QApplication.translate(
            "tilauscope_roast_assistant", "⚙ AUTO · Burner → {0}% (dev, rate-limited)")
        self._tpl_ap_net = QApplication.translate("tilauscope_roast_assistant", "⚙ AUTO · crash net — AIR {0}%")
        self._tr_ap_net_exhausted = QApplication.translate(
            "tilauscope_roast_assistant", "⚠ RoR crash — safety net exhausted, AUTO paused — take over")
        self._tr_ap_mode_ff = QApplication.translate("tilauscope_roast_assistant", "feedforward only")
        self._tr_ap_mode_trim = QApplication.translate("tilauscope_roast_assistant", "feedforward + trim")

        # Historique RoR : tendance ([-5:]) ET fenêtre 15 s du détecteur de crash
        # dev — 64 valeurs couvrent 15 s même à l'échantillonnage le plus rapide
        # (dt 0,25 s) ; les helpers de tendance/lissage tranchent en nombre fixe.
        self._ror_hist: deque[float] = deque(maxlen=64)

        # Dernières valeurs reçues via les signaux du bridge
        self._last_bt:  float = 0.0
        self._last_et:  float = 0.0
        self._last_ror: float = 0.0

        # Détecteur de crash RoR (réinitialisé à chaque changement de phase)
        self._crash_detector = _RoRCrashDetector()

        # create link with advisor
        self.roast_context = None
        if self.aw.tilau_roaster and self.aw.tilau_roaster != 'None':
            self.roast_context = RoasterManager().get_roast_context(self.aw.tilau_roaster)
        self.advisor = RoasterPhysicsAdvisor(self.roast_context)
        # Advisor tips are invariant for a phase (they depend only on the
        # roaster context, fixed for the panel's lifetime). Cache the joined
        # string per phase so the 1 Hz refresh never re-runs the advisor.
        self._advisor_tips_cache: dict[int, str] = {}
        # Cache the resolved RoasterContext (and inlet air path) on aw so the
        # phase pages can gate their control sliders without a signature change.
        self.aw._tilau_roast_context = self.roast_context
        # Cache the inlet air path (push/pull) for the pages' pull-aware advice.
        self.aw._tilau_inlet_air_mode = (
            getattr(self.roast_context, "inlet_air_mode", "push") if self.roast_context is not None else "push")
        # Lag actionneur→BT de la machine : fenêtre du débounce burner.        ## TILAU ##
        # RECALÉ sur le banc (étude 1, item E) : l'effet du feu est un
        # intégrateur LENT — mi-effet ~25-30 s, plein effet 60 s+, BT lisible
        # 60-90 s. L'ancien 15+45×(1−resp) (SW ≈ 28 s) rejugeait deux fois trop
        # tôt = mécanisme du pompage. 30 s (resp→1) à 120 s (resp→0) — Skywalker
        # (0.75) ≈ 53 s, Hottop (≈0.2) ≈ 102 s. La reprise anticipée si l'écart
        # se creuse et la chaîne crash (jamais débouncée) restent inchangées.
        _resp = float(getattr(self.roast_context, "thermal_response_speed", 0.5) or 0.5)
        self._heater_lag_s: float = 30.0 + 90.0 * (1.0 - max(0.0, min(1.0, _resp)))
        self.aw._tilau_burner_watch = None

        # Coefficients couleur (lus depuis QSettings — mêmes defaults que beancave)
        from PyQt6.QtCore import QSettings
        settings = QSettings()
        self._c0    = float(settings.value("RoastColor/C0_Interception",  328.67))
        self._c_bt  = float(settings.value("RoastColor/C_BT",             -1.55))
        self._c_dtr = float(settings.value("RoastColor/C_DTR",            -0.06))
        self._c_wl  = float(settings.value("RoastColor/C_WL",             -3.61))

        # ── Flags fenêtre flottante ────────────────────────────────────────────
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(420)

        self._build_ui()
        self._connect_signals()

        # Positionnement initial (à droite de la fenêtre parente)
        QTimer.singleShot(100, self._initial_position)

        # Dragging
        self._drag_origin = QPoint()

    # ── Construction UI ────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(5, 5, 5, 5)
        outer.setSpacing(0)

        # Container avec border + radius
        self._container = QFrame()
        self._container.setObjectName("AssistantContainer")
        self._container.setStyleSheet(f"""
            #AssistantContainer {{
                background: {_BG};
                border: 2px solid {_BORDER};
                border-radius: 14px;
            }}
            QToolTip {{
                background: #2D2F3F; color: white;
                border: 1px solid {_BORDER};
                padding: 4px; border-radius: 3px; font-size: 11px;
            }}
        """)
        outer.addWidget(self._container)

        inner = QVBoxLayout(self._container)
        inner.setContentsMargins(0, 0, 0, 8)
        inner.setSpacing(0)

        # ── Barre titre ───────────────────────────────────────────────────────
        title_bar = QFrame()
        title_bar.setStyleSheet(
            f"background: {_SURFACE}; border-top-left-radius: 12px; "
            f"border-top-right-radius: 12px; border-bottom: 1px solid {_BORDER};"
        )
        tb_layout = QHBoxLayout(title_bar)
        tb_layout.setContentsMargins(12, 6, 8, 6)
        lbl_title = QLabel(QApplication.translate("tilauscope_roast_assistant","◉  ROAST ASSISTANT"))
        lbl_title.setStyleSheet(
            f"color: {_ACCENT}; font-size: 11px; font-weight: 900; {_FONT} border: none;"
        )
        btn_close = QPushButton("✕")
        btn_close.setFixedSize(22, 22)
        btn_close.setStyleSheet(f"""
            QPushButton {{ background: #313244; color: #F38BA8;
                border-radius: 11px; border: 1px solid #F38BA8;
                font-weight: bold; font-size: 10px; }}
            QPushButton:hover {{ background: #F38BA8; color: {_BG}; }}
        """)
        btn_close.clicked.connect(self.hide_from_button)
        tb_layout.addWidget(lbl_title)
        tb_layout.addStretch()
        tb_layout.addWidget(btn_close)
        inner.addWidget(title_bar)

        # ── Movable body (setup + header + phase stack) ## TILAU ## ───────────
        # Held in a dedicated widget so it can be detached from this floating
        # shell and embedded into the TilauScope main panel (anchored mode)
        # without touching any signal/bridge wiring.
        self._inner = inner
        self._body  = QWidget()
        self._body.setObjectName("AssistantBody")
        # True while the body is reparented into the anchored host (guided
        # default): sizing is then owned by the host QScrollArea and this shell
        # is hidden, so the per-refresh height fit must skip.  ## TILAU ##
        self._body_detached = False
        # Explicit background so the body stays themed in BOTH the floating shell
        # and the anchored host, and survives reparenting through QScrollArea
        # (which otherwise leaves it painting the default palette → white).
        self._body.setStyleSheet(
            f"#AssistantBody {{ background: {_BG}; border: none; }}"
            # Dark tooltip applied at body level so every descendant keeps it,
            # including when the body is reparented into the anchored host.
            f"QToolTip {{ background-color: #2D2F3F; color: white;"
            f" border: 1px solid #585B70; padding: 5px;"
            f" border-radius: 3px; font-size: 11px; }}")
        self._body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        body_lay = QVBoxLayout(self._body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(0)

        # ── Barre de setup ────────────────────────────────────────────────────
        self._setup_bar = _SetupBar()
        body_lay.addWidget(self._setup_bar)

        # ── En-tête grain actif ───────────────────────────────────────────────
        self._bean_header = _BeanHeader()
        body_lay.addWidget(self._bean_header)
        ## TILAU ## AutoPilot : RETIRÉ de l'accès utilisateur (décision Tilau
        ## 2026-07-11, post-roast La Fabrica — le sujet repart de zéro sur le
        ## banc, doctrine settings-first). La puce n'est jamais visible tant que
        ## _AP_USER_ENABLED est False ; sans elle, l'état « armed » est
        ## inatteignable et tous les chemins AUTO (feedforward, trim, cockpit,
        ## automark, auto-DROP, cooling) sont morts. Le code reste en place pour
        ## la reprise. Garde-fou read-only conservé pour la ré-activation.
        ## TILAU ## the header must mirror the current selection as soon as it
        ## changes: it used to say "no green bean selected" while the dropdown
        ## already showed the bean identified from the roast record.
        self._setup_bar.combo_bean.currentIndexChanged.connect(self._on_setup_selection_changed)
        self._setup_bar.combo_agtron.currentIndexChanged.connect(self._on_setup_selection_changed)
        self._bean_header.btn_auto.clicked.connect(self._ap_toggle)
        self._bean_header.btn_auto.setVisible(
            _AP_USER_ENABLED and not _roaster_is_readonly(self.aw))

        # ── Pages de phases (QStackedWidget) ─────────────────────────────────
        self._stack = QStackedWidget()
        self._stack.setContentsMargins(10, 10, 10, 4)

        self._page_idle    = _IdlePage(self.aw)
        self._page_dry     = _DryingPage(self.aw)
        self._page_mai     = _MaillardPage(self.aw)
        self._page_dev     = _DevelopmentPage(self.aw)
        self._page_preheat = _PreheatPage(self.aw)
        self._page_drop    = _CoolingPage(self.aw)

        self._page_cockpit = _AutoCockpitPage(self.aw)   ## TILAU ## vue AUTO (v6)

        self._stack.addWidget(self._page_idle)     # index 0
        self._stack.addWidget(self._page_dry)      # index 1
        self._stack.addWidget(self._page_mai)      # index 2
        self._stack.addWidget(self._page_dev)      # index 3
        self._stack.addWidget(self._page_preheat)  # index 4
        self._stack.addWidget(self._page_drop)     # index 5
        self._stack.addWidget(self._page_cockpit)  # index 6 = _PAGE_COCKPIT ## TILAU ##
        self._page_cockpit.btn_ms.clicked.connect(self._ap_ms_clicked)      ## TILAU ##
        self._page_cockpit.lever_tapped.connect(self._ap_tile_tapped)       ## TILAU ##

        self._stack.setCurrentIndex(0)
        self._stack.currentChanged.connect(self._on_page_changed)

        body_lay.addWidget(self._stack, 1)   ## TILAU ##
        inner.addWidget(self._body, 1)       ## TILAU ##
        self._fit_stack_to_current(0)        ## TILAU ## collapse inactive pages

    # ── Connexions signaux ─────────────────────────────────────────────────────

    def _connect_signals(self) -> None:
        self._bean_header.btn_toggle.clicked.connect(self._on_toggle)
        self._setup_bar.btn_anchor.clicked.connect(self.anchor_requested)   ## TILAU ##
        # End of Roast actions
        self._page_drop._eor_btn_result.clicked.connect(self._on_open_result_form)
        self._page_drop._eor_btn_notes.clicked.connect(self._on_open_notes)
        self._page_drop._eor_btn_exclude.toggled.connect(self._on_toggle_exclude_learning)

    def _on_toggle_exclude_learning(self, checked: bool) -> None:
        """Pose/retire le veto d'apprentissage sur le roast courant. Le flag
        est stocké sur qmc et persisté dans l'alog par le save d'Artisan
        (getProfile) — l'analyse historique du plan saute alors ce fichier."""
        try:
            self.aw.qmc.tilau_exclude_learning = bool(checked)
            _logd.info(f"RoastAssistant: exclude-from-learning = {checked}")
        except Exception:  # pylint: disable=broad-except
            pass

    def set_panel_anchor_visible(self, visible: bool) -> None:
        """Show/hide the panel-side anchor toggle (Guided level only). ## TILAU ##"""
        self._setup_bar.btn_anchor.setVisible(visible)

    def set_operator_level(self, level: str) -> None:  ## TILAU ##
        """Propagate operator level into the assistant panel. ## TILAU ##
        Guided: hide start/stop button (Artisan controls the assistant).
        Expert: show start/stop button (manual control).
        """
        self._operator_level = level
        self._bean_header.set_start_stop_visible(level != "guided")
        self._page_idle.set_operator_level(level)

    def _minutes_since_last_drop(self) -> "float | None":
        """Minutes écoulées (wall clock) depuis le dernier DROP de la session —
        stampé par displayscope sur aw. None au batch 1 (aucun drop encore) :
        le plan n'applique alors aucune correction heat-soak."""
        try:
            t = getattr(self.aw, "_tilau_last_drop_wall", None)
            return (time.time() - float(t)) / 60.0 if t else None
        except (TypeError, ValueError):
            return None

    def _build_soak_note(self) -> None:
        """Met en cache la ligne heat-soak affichée par la page preheat (les
        traductions ne doivent pas être refaites à chaque tick 1 Hz)."""
        self._soak_note = None
        try:
            hs = (self._plan or {}).get("Heat Soak")
            if hs:
                self._soak_note = QApplication.translate(
                    "tilauscope_roast_assistant",
                    "heat soak {0}° · heater {1}% (drop {2} min ago)").format(
                    f"{float(hs['dcharge']):+.1f}", f"{int(hs['dheater']):+d}",
                    f"{float(hs['mins']):.0f}")
        except (KeyError, TypeError, ValueError):
            self._soak_note = None

    def _charge_weight_g(self, fallback: float = 400.0) -> float:
        """
        qmc.weight[0] converti en GRAMMES.

        qmc.weight est exprimé dans l'unité choisie par l'utilisateur
        (qmc.weight[2] ∈ weight_units ; setProfile convertit tout profil vers
        cette unité au chargement). Toute la chaîne plan/historique travaille
        en grammes — la conversion doit se faire ici, à la frontière qmc.
        """
        try:
            try:
                idx = weight_units.index(self.aw.qmc.weight[2])
            except ValueError:
                idx = 0   # unité inconnue → grammes
            w = convertWeight(float(self.aw.qmc.weight[0] or 0.0), idx, 0)
            return float(w) if w and w > 0 else fallback
        except (ValueError, TypeError, IndexError, AttributeError):
            return fallback

    def _on_open_result_form(self) -> None:
        """Ouvre RoastResultDialog — même logique que displayscope._open_roast_result_dialog."""
        try:
            from tilauscope.roast_properties import RoastResultDialog
            bean = self._bean or __import__('tilauscope.tilauscope_types', fromlist=['GreenBean']).GreenBean()
            # RoastResultDialog attend des grammes (champ formaté {:.0f})
            green_weight = self._charge_weight_g(fallback=0.0)
            dlg = RoastResultDialog(bean, self.aw, green_weight=green_weight)
            dlg.exec()
        except Exception as e:
            _logd.warning(f"RoastAssistant: open result form failed: {e}")

    def _on_open_notes(self) -> None:
        """Ouvre un simple dialog de notes texte libre."""
        try:
            from PyQt6.QtWidgets import QInputDialog
            note, ok = QInputDialog.getMultiLineText(
                self,
                QApplication.translate("tilauscope_roast_assistant", "Roast Notes"),
                QApplication.translate("tilauscope_roast_assistant", "Add notes for this roast:"),
                self.aw.qmc.roastingnotes or "",
            )
            if ok:
                self.aw.qmc.roastingnotes = note
        except Exception as e:
            _logd.warning(f"RoastAssistant: open notes failed: {e}")

    @pyqtSlot(int)
    def _on_page_changed(self, index: int) -> None:
        """Resize panel to active page without triggering Windows MINMAXINFO conflict."""
        self._fit_stack_to_current(index)   ## TILAU ##
        QTimer.singleShot(50, self._apply_panel_height)

    def _fit_stack_to_current(self, index: int) -> None:
        """Make the stack request only the current page's height ## TILAU ##.

        QStackedWidget otherwise sizes to the tallest page, forcing a scrollbar
        once the body is embedded in the anchored host. Collapsing inactive
        pages vertically lets the host (and the floating window) fit the visible
        page exactly.
        """
        for i in range(self._stack.count()):
            v = (QSizePolicy.Policy.Preferred if i == index
                 else QSizePolicy.Policy.Ignored)
            self._stack.widget(i).setSizePolicy(QSizePolicy.Policy.Preferred, v)

    def _adjust_size_if_needed(self) -> None:
        """Recalculate height only when content changes — 1 Hz safe."""
        self._apply_panel_height()

    def _apply_panel_height(self) -> None:
        """Set window height from sizeHint without calling adjustSize() (Windows-safe)."""
        # Anchored (guided default): the body lives in the host QScrollArea
        # (widgetResizable) which owns sizing, and this shell is hidden —
        # recomputing its sizeHint / resizing it every refresh is pure waste.
        # Only the floating window needs to be fitted to its content.  ## TILAU ##
        if self._body_detached:
            return
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)  # QWIDGETSIZE_MAX — release any prior lock
        h = self.sizeHint().height()
        if abs(self.height() - h) > 4:
            self.resize(self.width(), h)

    # ── Position initiale ──────────────────────────────────────────────────────

    def _initial_position(self) -> None:
        if self._parent:
            self.move(230,150)

    # ── Drag ──────────────────────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event) -> None:
        if not self._drag_origin.isNull():
            delta = event.globalPosition().toPoint() - self._drag_origin
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self._drag_origin = event.globalPosition().toPoint()

    # ── Toggle Start / Stop ────────────────────────────────────────────────────

    @pyqtSlot()
    def _on_toggle(self) -> None:
        pressed = self._bean_header.btn_toggle.isChecked()
        if pressed:
            self._start_assistant()
        else:
            self._stop_assistant()

    def _refresh_bean_header(self) -> None:   ## TILAU ##
        """Mirror the current setup selection in the bean header.

        Single point of truth for the idle header: while no roast is running the
        header shows whatever the dropdowns hold (the bean identified from the
        roast record, or the operator's own pick). During a roast the header is
        owned by _start_assistant and must not be touched.
        """
        if self.is_active:
            return
        self._bean_header.update_bean(self._setup_bar.selected_bean(),
                                      self._setup_bar.selected_agtron())

    def _on_setup_selection_changed(self, _idx: int) -> None:   ## TILAU ##
        self._refresh_bean_header()

    def _start_assistant(self) -> None:
        """Charge les données du grain sélectionné et génère le plan prédictif."""
        bean = self._setup_bar.selected_bean()
        agtron = self._setup_bar.selected_agtron()

        if bean is None or agtron is None:
            _logd.warning("RoastAssistant: grain ou Agtron non sélectionné")
            self._bean_header.btn_toggle.setChecked(False)
            return

        self._bean   = bean
        self._agtron = agtron
        self._plan   = None
        self._plan_initial = None         ## TILAU ## plan vivant : reset session
        self._replans_applied = []        ## TILAU ##
        self._replan_attempted = set()    ## TILAU ##
        self._replan_notice = None        ## TILAU ##
        self._burner_last_pct = None      ## TILAU ##
        self.aw._tilau_burner_watch = None  ## TILAU ##
        ## TILAU ## AutoPilot : l'armement est un opt-in PAR SESSION — jamais hérité
        self._ap_set_state("off")
        self._ap_notice = None
        self._ap_last_action = None
        self._ap_lever_flash.clear()
        self._ap_automark_done.clear()
        self._ap_drop_deadline = None
        self._ap_drop_cancelled = False
        # Nouveau roast → le veto d'apprentissage de la session précédente tombe
        # (il ne se reset PAS au stop : le toggle se pose au bilan EOR, après
        # l'arrêt de l'enregistrement, et doit survivre jusqu'au save).
        self.aw.qmc.tilau_exclude_learning = False
        # A plan snapshot belongs to one roast. Do not erase a completed roast
        # merely because the panel was reopened before RESET. ## TILAU ##
        if self.aw.qmc.timeindex[0] < 0:
            self.aw.qmc.tilau_roast_plan_snapshot = None
        try:
            self._page_drop._eor_btn_exclude.setChecked(False)
        except (AttributeError, RuntimeError):
            pass
        self._ror_hist.clear()
        self._crash_detector.reset()
        self._page_dry.ao._color_hist.clear()
        self._page_dry.ao._roc_hist.clear()
        self._page_preheat._charge_btn_latched = False   # reset latch pour cette session


        # Tentative de génération du plan prédictif
        try:
            dev = self._read_probe_deviation()

            # Nouvelle session → nouveau générateur (cache historique vierge)
            self._rp = TilauScopeRoastPlan(parent=self.aw, roaster_ctx=self.roast_context)
            rp = self._rp
            ambient_temp  = float(self.aw.qmc.ambientTemp
                                  or (20.0 if self.aw.qmc.mode == 'C' else fromCtoFstrict(20.0)))
            ambient_hum   = float(self.aw.qmc.ambient_humidity or 60.0)
            charge_weight = self._charge_weight_g()   # qmc.weight[2] → grammes
            roast_alt     = float(self.aw.qmc.roastertype_setup_altitude
                                  if hasattr(self.aw.qmc, "roastertype_setup_altitude")
                                  else 0.0)

            plan_dict, *_ = rp.generate_roast_plan(
                bean=bean,
                agtron_target=agtron,
                ambient_temp=ambient_temp,
                ambient_humidity=ambient_hum,
                charge_weight=charge_weight,
                roast_altitude=roast_alt,
                bt_deviation=dev,
                airwave_present=getattr(self.aw, "bleAirwaveDevice", None) is not None,
                minutes_since_last_drop=self._minutes_since_last_drop(),
            )
            self._plan = plan_dict
            self._plan_initial = plan_dict   ## TILAU ## référence figée pour le bilan EOR
            self._capture_prediction_snapshot(plan_dict)  ## TILAU ## P2 pre-roast truth
            self._build_soak_note()
            _logd.debug(
                f"RoastAssistant: plan généré pour {bean.name} → {agtron.name}"
            )
        except Exception as e:
            _logd.warning(f"RoastAssistant: plan indisponible ({e})")
            self._plan = None
            self._plan_initial = None        ## TILAU ##

        self.is_active = True
        self._setup_bar.set_active(True)
        self._setup_bar.show_combos(False)
        self._bean_header.set_active(True)
        self._bean_header.update_bean(bean, agtron)
        if self.aw.qmc.flagon and self.aw.qmc.flagstart:
            # Sentinel convention: ti[0]==-1 means CHARGE unmarked;        ## TILAU ##
            # milestones 1..7 use 0 as "unmarked", >0 as "marked".         ## TILAU ##
            # Resolve from latest milestone backward (bug fix: previous     ## TILAU ##
            # code tested ==-1 on 1..6 and fell through to summary).        ## TILAU ##
            ti = self.aw.qmc.timeindex                                      ## TILAU ##
            if ti[0] == -1:
                self._current_phase = self._PHASE_PREHEAT
            elif ti[6] > 0:        # DROP marked -> cooling / summary       ## TILAU ##
                self._current_phase = self._PHASE_DROP
            elif ti[2] > 0:        # FC START marked -> development         ## TILAU ##
                self._current_phase = self._PHASE_DEV
            elif ti[1] > 0:        # DRY END marked -> maillard             ## TILAU ##
                self._current_phase = self._PHASE_MAI
            else:                  # CHARGE marked only -> drying           ## TILAU ##
                self._current_phase = self._PHASE_DRY
            self._stack.setCurrentIndex(self._current_phase)
            # Démarrage tardif : recale immédiatement le plan vivant sur les  ## TILAU ##
            # jalons déjà marqués (le TP est repris au prochain tick refresh). ## TILAU ##
            if ti[1] > 0:                                                    ## TILAU ##
                self._replan_at_milestone("dry_end", 1)                      ## TILAU ##
            if ti[2] > 0:                                                    ## TILAU ##
                self._replan_at_milestone("fc_start", 2)                     ## TILAU ##
        else:
            self._current_phase = self._PHASE_IDLE
            self._stack.setCurrentIndex(self._PHASE_IDLE)

    def _stop_assistant(self) -> None:
        self.is_active = False
        self._rp = None   # libère le générateur et son cache historique
        # Désarme la relance back-to-back : un armement ne doit jamais
        # survivre à la session (tir surprise au cooling du roast suivant).
        try:
            self._page_drop._relaunch_armed = False
        except (AttributeError, RuntimeError):
            pass
        self._setup_bar.set_active(False)
        self._setup_bar.show_combos(True)
        self._bean_header.set_active(False)
        self._refresh_bean_header()   ## TILAU ## keep showing what is selected
        self._current_phase = self._PHASE_IDLE
        self._stack.setCurrentIndex(self._PHASE_IDLE)
        self._ror_hist.clear()
        self._bt_at_fcs = 0.0
        self._plan_initial = None         ## TILAU ##
        self._replans_applied = []        ## TILAU ##
        self._replan_attempted = set()    ## TILAU ##
        self._replan_notice = None        ## TILAU ##
        self._burner_last_pct = None      ## TILAU ##
        self.aw._tilau_burner_watch = None  ## TILAU ##
        ## TILAU ## AutoPilot : désarmé au stop, toujours (garde-fou §6)
        self._ap_set_state("off")
        self._ap_notice = None
        self._ap_last_action = None
        self._ap_lever_flash.clear()
        self._ap_automark_done.clear()
        self._ap_drop_deadline = None
        self._ap_drop_cancelled = False

    # ── API publique appelée par TilauScope ────────────────────────────────────

    def set_phase(self, phase_key: str) -> None:
        """
        Appelé par TilauScope._handle_milestone_events() pour synchroniser la phase.
        phase_key : "DRY" | "MAI" | "DEV" | "COOL" | "PREHEAT" | "DROP"
        """
        if not self.is_active:
            return
        new_phase = self._PHASE_MAP.get(phase_key, self._PHASE_IDLE)
        if new_phase == self._current_phase:
            return
        self._current_phase = new_phase
        self._stack.setCurrentIndex(new_phase)
        # Repaint COMPLET one-shot de la page qui s'active : les labels ont des  ## TILAU ##
        # gardes anti-repaint (no-op si texte inchangé) sur fond transparent —   ## TILAU ##
        # sans ce coup de pinceau, des pixels de la page précédente pouvaient    ## TILAU ##
        # rester visibles dessous (chevauchement observé au passage FC).         ## TILAU ##
        _w = self._stack.currentWidget()                                         ## TILAU ##
        if _w is not None:                                                       ## TILAU ##
            _w.update()                                                          ## TILAU ##
        self._sync_stack_page()   ## TILAU ## cockpit si AUTO pilote
        self._crash_detector.reset(mode=self.aw.qmc.mode)  # nouvelle phase → reset + mode

        # Plan vivant : re-ancre la courbe restante sur le jalon réel qui       ## TILAU ##
        # vient d'être marqué (événementiel — jamais dans le hot path 1 Hz).    ## TILAU ##
        if phase_key == "MAI":                                                  ## TILAU ##
            self._replan_at_milestone("dry_end", 1)                             ## TILAU ##
        elif phase_key == "DEV":                                                ## TILAU ##
            self._replan_at_milestone("fc_start", 2)                            ## TILAU ##

        ## TILAU ## AutoPilot : feedforward au jalon, APRÈS le replan (les valeurs
        ## posées doivent être celles du plan vivant re-ancré). Événementiel.
        if self._ap_state == "armed":
            if phase_key in _AP_PHASE_COL:
                if phase_key == "DRY":   ## TILAU ## seam CHARGE : ouvre la fenêtre de grâce
                    self._ap_charge_settle_until = time.monotonic() + _AP_CHARGE_SETTLE_S
                self._ap_apply_phase(phase_key)
                self._ap_core_start_phase(phase_key)   # trim v1b : cibles fraîches, trims à zéro
            elif phase_key in ("DROP", "COOL"):
                self._ap_apply_cooling()   # burner 0, air/ext forts, drum rapide, puis off

        # En entrant en COOL, forcer la lecture directe de qmc pour peupler
        # _last_bt/et/ror immédiatement (le bridge peut avoir arrêté d'émettre après DROP)
        if new_phase == self._PHASE_DROP:
            try:
                qmc = self.aw.qmc
                bt = float(qmc.temp2[-1])
                et = float(qmc.temp1[-1])
                if bt > 0:
                    self._last_bt = bt
                if et > 0:
                    self._last_et = et
            except (IndexError, TypeError, AttributeError):
                pass

        # Capture BT au FC START pour ΔT DEV
        if phase_key == "DEV":
            try:
                self._bt_at_fcs = float(self.aw.qmc.temp2[-1])
            except (IndexError, TypeError):
                self._bt_at_fcs = 0.0

        # Paint the freshly-activated page immediately, without waiting for the
        # next bridge tick (which may have stopped after DROP or on pause). ## TILAU ##
        self._refresh_current_page()

    def set_preheating(self, active: bool) -> None:
        """
        Appelé par TilauScope.handle_preheat(show) pour entrer / quitter
        la page de préchauffage.

        active=True  → bascule sur la page _PreheatPage
        active=False → si on était en préchauffage, repasse sur Idle en
                        attendant que set_phase("DRY") soit appelé par CHARGE.
        """
        if not self.is_active:
            return
        if active:
            if self._current_phase != self._PHASE_PREHEAT:
                self._current_phase = self._PHASE_PREHEAT
                self._stack.setCurrentIndex(self._PHASE_PREHEAT)
        else:
            # Retour à Idle : set_phase("DRY") prendra le relai dès le CHARGE
            if self._current_phase == self._PHASE_PREHEAT:
                self._current_phase = self._PHASE_IDLE
                self._stack.setCurrentIndex(self._PHASE_IDLE)

    # ── Connexion au RoastDataBridge ──────────────────────────────────────────

    def connect_bridge(self, bridge: "RoastDataBridge") -> None:
        """
        Branche l'assistant sur le bridge de signaux.
        Appelé depuis TilauScope.__init_ui__() après instanciation du bridge.
        Remplace l'ancien on_artisan_update() en polling.
        """
        bridge.bt_updated.connect(self._on_bt)
        bridge.et_updated.connect(self._on_et)
        bridge.ror_updated.connect(self._on_ror)
        bridge.phase_changed.connect(self.set_phase)
        bridge.ambient_updated.connect(self._on_ambient_changed)
        bridge.roast_state_changed.connect(self._on_roast_state)
        _logd.debug("RoastAssistantPanel: connected to RoastDataBridge")

    def update_batch(self) -> None:
        """Refresh the live batch badge from qmc (call on DROP / batch edits)."""
        qmc = self.aw.qmc
        self._bean_header.update_batch(
            getattr(qmc, "roastbatchprefix", "#"),
            getattr(qmc, "roastbatchnr", 0),
            getattr(qmc, "roastbatchpos", 1),
        )

    # ── Slots du bridge ────────────────────────────────────────────────────────

    @pyqtSlot(float)
    def _on_bt(self, bt: float) -> None:
        if not self.is_active or self._current_phase == self._PHASE_IDLE:
            return
        self._last_bt = bt
        self._refresh_current_page()

    @pyqtSlot(float)
    def _on_et(self, et: float) -> None:
        if not self.is_active or self._current_phase == self._PHASE_IDLE:
            return
        self._last_et = et

    @pyqtSlot(float)
    def _on_ror(self, ror: float) -> None:
        if not self.is_active or self._current_phase == self._PHASE_IDLE:
            return
        self._last_ror = ror
        self._ror_hist.append(ror)

    @pyqtSlot(float, float)
    def _on_ambient_changed(self, temp: float, hum: float) -> None:
        """
        Reçu depuis RoastDataBridge quand l'ambiant change significativement.
        Régénère le plan uniquement si on est encore en PREHEAT ou DRY.
        """
        if not self.is_active:
            return
        if self._current_phase not in (self._PHASE_PREHEAT, self._PHASE_DRY):
            return
        if self._bean is None or self._agtron is None:
            return

        _logd.debug(
            f"RoastAssistant: ambient change T={temp:.1f} H={hum:.1f} "
            f"→ regenerating plan (phase={self._current_phase})"
        )
        self._regenerate_plan(ambient_temp=temp, ambient_hum=hum)

    @pyqtSlot(bool)
    def _on_roast_state(self, active: bool) -> None:
        if not active and self.is_active:
            self._stop_assistant()
        elif active and not self.is_active and (
                self._operator_level == "guided"          # Guided : auto-start systématique
                or self._relaunch_requested):             # relance back-to-back : tous niveaux
            self._relaunch_requested = False
            self._start_assistant()

    # ── Régénération partielle du plan ─────────────────────────────────────────

    def _capture_prediction_snapshot(self, plan: dict) -> None:
        """Freeze the latest plan only while CHARGE is still unmarked. ## TILAU ##"""
        qmc = self.aw.qmc
        if qmc.timeindex[0] >= 0:
            return
        if qmc.roastUUID is None:
            qmc.roastUUID = uuid.uuid4().hex
        target = self._agtron
        if target is None:
            return
        target_mid = (target.agtron_range.min_value + target.agtron_range.max_value) / 2.0
        qmc.tilau_roast_plan_snapshot = build_prediction_snapshot(
            plan, plan_id=qmc.roastUUID, target_color_agtron=target_mid,
            expected_color_basis="ground", mode=qmc.mode)

    def _read_probe_deviation(self):
        """
        Lit la déviation sonde manuelle depuis QSettings (groupe ProbeDeviation).
        Source UNIQUE pour _start_assistant et _regenerate_plan — les deux
        générations d'une même session doivent utiliser la même correction.
        Retourne None si l'override manuel n'est pas activé.

        DOCTRINE unité : les offsets sont TOUJOURS en °C (même frame que
        RoasterContext.bt_offsets), quel que soit le mode Artisan — le plan
        les additionne à ses valeurs internes °C. L'UI BeanCave les étiquette
        « (°C) ».
        """
        from tilauscope.tilauscope_types import ProbeDeviation, ProbeDeviationInterval
        from PyQt6.QtCore import QSettings

        settings = QSettings()
        settings.beginGroup("ProbeDeviation")
        def _read_dev(key):
            s = settings.value(f"{key}_start", 0.0, type=float)
            e = settings.value(f"{key}_end",   0.0, type=float)
            return ProbeDeviationInterval(s, e)
        dev = None
        if settings.value("ManualProbeSettings", False, bool):
            dev = ProbeDeviation(
                probe_id="default",
                bt_at_charge=_read_dev("bt_at_charge"),
                bt_at_de=_read_dev("bt_at_de"),
                bt_at_fc=_read_dev("bt_at_fc"),
                bt_at_drop=_read_dev("bt_at_drop"),
            )
        settings.endGroup()
        return dev

    def _regenerate_plan(self, ambient_temp: float, ambient_hum: float) -> None:
        """Régénère le plan prédictif avec des valeurs ambiantes mises à jour."""
        try:
            dev = self._read_probe_deviation()

            qmc = self.aw.qmc
            # Réutilise le générateur de la session : même grain/cible/poids →
            # l'analyse historique sort du cache au lieu de relire les .alog.
            rp = self._rp
            if rp is None:
                rp = TilauScopeRoastPlan(parent=self.aw, roaster_ctx=self.roast_context)
                self._rp = rp
            charge_weight = self._charge_weight_g()   # qmc.weight[2] → grammes

            plan_dict, *_ = rp.generate_roast_plan(
                bean=self._bean,
                agtron_target=self._agtron,
                ambient_temp=ambient_temp,
                ambient_humidity=ambient_hum,
                charge_weight=charge_weight,
                roast_altitude=float(
                    qmc.roastertype_setup_altitude
                    if hasattr(qmc, "roastertype_setup_altitude") else 0.0
                ),
                bt_deviation=dev,
                airwave_present=getattr(self.aw, "bleAirwaveDevice", None) is not None,
                minutes_since_last_drop=self._minutes_since_last_drop(),
            )
            self._plan = plan_dict
            self._plan_initial = plan_dict                                   ## TILAU ##
            self._capture_prediction_snapshot(plan_dict)                     ## TILAU ## P2
            self._build_soak_note()
            # Ré-applique les recalages jalons déjà actés (ex. TP pendant     ## TILAU ##
            # DRY) — sinon la régénération ambiante les effacerait.           ## TILAU ##
            for _m, _t, _bt in self._replans_applied:                         ## TILAU ##
                try:                                                          ## TILAU ##
                    self._plan = rp.replan_from_milestone(self._plan, _m, _t, _bt)  ## TILAU ##
                except Exception as _e:                                       ## TILAU ##
                    _logd.warning(f"RoastAssistant: replay replan {_m} failed ({_e})")  ## TILAU ##
            _logd.debug("RoastAssistant: plan regenerated successfully")
        except Exception as e:
            _logd.warning(f"RoastAssistant: plan regeneration failed ({e})")

    # ── Plan vivant : recalage aux jalons ──────────────────────────────────────  ## TILAU ##

    def _apply_replan(self, milestone: str, t_actual_min: float, bt_native: float) -> None:  ## TILAU ##
        """
        Applique un recalage jalon au plan VIVANT (jamais au plan initial).
        Le générateur re-fitte les ancres restantes (températures préservées,
        temps re-projetés) et renvoie un NOUVEAU dict — en cas d'ancre
        implausible il renvoie le plan inchangé et on ne journalise que le skip.
        """
        if not (self.is_active and self._plan and self._rp):
            return
        if any(m == milestone for m, _t, _b in self._replans_applied):
            return
        try:
            new_plan = self._rp.replan_from_milestone(
                self._plan, milestone, t_actual_min, bt_native)
        except Exception as e:  # pylint: disable=broad-except
            _logd.warning(f"RoastAssistant: replan {milestone} failed ({e})")
            return
        if new_plan is self._plan:
            _logd.debug(f"RoastAssistant: replan {milestone} skipped (implausible anchor)")
            return
        self._plan = new_plan
        self._replans_applied.append((milestone, float(t_actual_min), float(bt_native)))
        # Notice coach one-shot (informatif ~15 s ; warn si DTR hors bande).
        warn = new_plan.get("Replan Warning")
        note = new_plan.get("Replan Note")
        if warn:
            self._replan_notice = (str(warn), _S_WARN, time.monotonic() + 15.0)
        elif note:
            self._replan_notice = (str(note), _S_OK, time.monotonic() + 15.0)
        _logd.info(f"RoastAssistant: plan re-anchored → {new_plan.get('Replan Source')}")

    def _replan_at_milestone(self, milestone: str, ti_idx: int) -> None:  ## TILAU ##
        """
        Recalage depuis un événement Artisan marqué (ti_idx : 1=DRY END,
        2=FC START). One-shot : une tentative par jalon et par session,
        même si l'ancre est rejetée (pas de retry dans le hot path).
        """
        if milestone in self._replan_attempted:
            return
        self._replan_attempted.add(milestone)
        try:
            qmc = self.aw.qmc
            ti = qmc.timeindex
            # Sentinelles : ti[0] == -1 non marqué ; indices 1..7 : 0 = non marqué.
            if ti[0] > -1 and ti[ti_idx] > 0 and ti[ti_idx] < len(qmc.timex):
                t_min = (float(qmc.timex[ti[ti_idx]]) - float(qmc.timex[ti[0]])) / 60.0
                bt = float(qmc.temp2[ti[ti_idx]])
                if bt > 0:
                    self._apply_replan(milestone, t_min, bt)
        except Exception as e:  # pylint: disable=broad-except
            _logd.debug(f"RoastAssistant: replan trigger {milestone} skipped ({e})")

    # ── Aggregation des données courantes pour refresh ─────────────────────────

    def _collect_qmc_context(self) -> dict:
        """
        Collecte les données contextuelles depuis qmc (non émises par le bridge).
        Appelé uniquement au moment du refresh de page — une seule fois par cycle.
        """
        qmc = self.aw.qmc
        ctx: dict = {
            "bt":     self._last_bt,
            "et":     self._last_et,
            "ror":    self._last_ror,
            "mode":   qmc.mode,
            "phases": qmc.phases,
            "ti":     qmc.timeindex,
            "tx":     qmc.timex,
        }
        # Timestamps clés depuis CHARGE
        def _ts(idx: int) -> float:
            try:
                ti = ctx["ti"]
                tx = ctx["tx"]
                ref = tx[ti[0]] if ti[0] > -1 else 0.0
                return tx[ti[idx]] - ref if ti[idx] > -1 else 0.0
            except (IndexError, TypeError):
                return 0.0

        try:
            ti = ctx["ti"]
            tx = ctx["tx"]
            if ti[0] > -1:
                # t_now_sec dans le même référentiel que t_fcs_sec et t_dryend_sec :
                # on prend la dernière valeur de timex moins le timex au CHARGE.
                # tx[-1] est toujours la dernière mesure enregistrée par Artisan.
                ref = tx[ti[0]]
                ctx["t_now_sec"] = float(tx[-1]) - ref if tx else 0.0
            else:
                ctx["t_now_sec"] = 0.0
        except (IndexError, TypeError):
            ctx["t_now_sec"] = 0.0

        ctx["t_dryend_sec"] = _ts(1)
        ctx["t_fcs_sec"]    = _ts(2)
        ctx["t_drop_sec"]   = _ts(6)

        # Turning Point — utilisé par la page DRY pour supprimer les fausses alertes
        # pendant la chute post-charge et la reconstruction du RoR.
        # TPalarmtimeindex est l'index dans timex où Artisan a détecté le TP (-1 si absent).
        try:
            tp_idx = getattr(qmc, 'TPalarmtimeindex', -1)
            ti     = ctx["ti"]
            tx     = ctx["tx"]
            if (tp_idx is not None and tp_idx > 0
                    and ti[0] > -1
                    and tp_idx < len(tx)):
                ctx["t_tp_sec"] = float(tx[tp_idx]) - float(tx[ti[0]])
            else:
                ctx["t_tp_sec"] = -1.0   # TP pas encore détecté
        except (IndexError, TypeError, AttributeError):
            ctx["t_tp_sec"] = -1.0

        return ctx

    # ── Dispatch de refresh par phase ──────────────────────────────────────────

    def _advisor_tips_for(self, phase: int) -> str:
        """Joined advisor tips for `phase`, computed once and cached.

        The advice depends only on the roaster context (fixed for the panel's
        lifetime), so the result is invariant for the whole phase — recomputing
        it (advisor + translate calls + join) every second was pure waste on the
        1 Hz refresh path. An empty string is a valid cached value.
        """
        cached = self._advisor_tips_cache.get(phase)
        if cached is None:
            tips = (self.advisor.get_phase_advice(phase, None)
                    if self.advisor.ctx is not None else [])
            cached = "  ·  ".join(tips) if tips else ""
            self._advisor_tips_cache[phase] = cached
        return cached

    # ── AutoPilot v1a — feedforward (AutoRoast-Spec §3 étage 1, §5, §6) ──────
    ## TILAU ## L'AutoPilot n'a aucun savoir propre : il applique les valeurs de
    ## phase du plan vivant (replan inclus) et les paliers de rampe heater, via
    ## le même chemin que l'humain (_apply_slider_value). Le trim continu
    ## (étage 2, autopilot_core) arrive en v1b.

    def _ap_watch_idxs(self) -> tuple[int, ...]:
        b = _burner_slider_idx(self.aw)
        return (0, 1, 2, b) if b not in (0, 1, 2) else (0, 1, 2)

    def _ap_trim_params(self) -> TrimParams:
        """Paramètres du trim pour ce torréfacteur.
        # TODO(v2): lire les surcharges pas/fenêtres/bornes depuis RoasterContext
        # et apprendre les magnitudes des roasts manuels (spec §3bis).
        Les défauts SONT la calibration Skywalker (Sim-1/Sim-2, 81 roasts) — la
        seule machine existante aujourd'hui ; le seam d'injection est ici."""
        return TrimParams()

    def _ap_core_start_phase(self, phase_key: str) -> None:
        """Démarre la phase du moteur de trim (MAI/DEV seulement — périmètre des
        sims). Cibles = reconstruction géométrique des moyennes du plan vivant
        (°C), durée = waypoints de la courbe. Appelé APRÈS le feedforward, pour
        que les valeurs observées soient celles fraîchement posées."""
        if phase_key not in ("MAI", "DEV"):
            return
        try:
            mode = self.aw.qmc.mode
            rs, re_ = _ap_phase_endpoints(self._plan, phase_key, mode)
            span = _ap_phase_span_sec(self._plan, phase_key) or 300.0
            t0 = float(self._collect_qmc_context()["t_now_sec"])
            aw_on = getattr(self.aw, "bleAirwaveDevice", None) is not None
            self._ap_core.start_phase(
                _APPhase.MAILLARD if phase_key == "MAI" else _APPhase.DEV,
                t0, t0 + span, rs, re_,
                {_APLever.AIR: _read_slider_pct(self.aw, 0),
                 _APLever.HEATER: _read_slider_pct(self.aw, _burner_slider_idx(self.aw)),
                 _APLever.EXT: _read_slider_pct(self.aw, 2) if aw_on else None})
            _logd.info(f"AutoPilot: trim engine phase {phase_key} "
                       f"target {rs:.1f}→{re_:.1f} °C/min over {span:.0f}s")
            if phase_key == "DEV":
                # ── « tenir le feu » : ancre du rate-limiter exotherme (t0 =    ## TILAU ##
                # entrée en dev / reprise, b0 = feu courant) + file feu vidée +  ## TILAU ##
                # filet réactif remis à zéro (nouvelle référence).               ## TILAU ##
                _b0 = _read_slider_pct(self.aw, _burner_slider_idx(self.aw))
                self._ap_dev_rate_anchor = (t0, float(_b0)) if _b0 is not None else None
                self._ap_dev_heater_pending = None
                self._ap_net_offset = 0.0
                self._ap_net_quiet_since = None
        except Exception:  # pylint: disable=broad-except
            _logd.warning("AutoPilot: trim engine start_phase failed", exc_info=True)

    def _ap_cockpit_active(self) -> bool:
        """Vue cockpit affichée : AUTO ARMÉ pendant une phase de roast.
        En PAUSE on revient aux pages détaillées : c'est la reprise en main —
        l'opérateur y retrouve les quick-adjust ± et les boutons de jalon
        (en mode ancré Guided les sliders Artisan ne sont pas visibles ;
        rester en cockpit l'enfermait sans aucun levier accessible)."""
        return (self._ap_state == "armed"
                and self._current_phase in (self._PHASE_DRY, self._PHASE_MAI,
                                            self._PHASE_DEV))

    def _sync_stack_page(self) -> None:
        """Choisit la page affichée : cockpit quand AUTO pilote, sinon la page
        de phase. Appelé aux changements d'état AUTO et de phase."""
        target = self._PAGE_COCKPIT if self._ap_cockpit_active() else self._current_phase
        if self._stack.currentIndex() != target:
            self._stack.setCurrentIndex(target)
            _w = self._stack.currentWidget()
            if _w is not None:
                _w.update()   # repaint one-shot (fantômes, cf. fix FC)

    def _ap_set_state(self, state: str) -> None:
        self._ap_state = state
        try:
            self._bean_header.set_auto_state(state)
        except (AttributeError, RuntimeError):
            pass
        if state == "off":
            self._ap_expected.clear()
            self._ap_core.disarm()   # v1b : plus d'action moteur possible jusqu'au prochain armement
            self._ap_dev_heater_pending = None   ## TILAU ## file feu + rate-limiter dev
            self._ap_dev_rate_anchor = None      ## TILAU ##
            self._ap_net_offset = 0.0            ## TILAU ## filet réactif
            self._ap_net_quiet_since = None      ## TILAU ##
        self._sync_stack_page()

    def _ap_resync(self) -> None:
        """Resynchronise l'observation des sliders sur leurs valeurs courantes —
        aucune actuation surprise à l'armement ni à la reprise (§5)."""
        self._ap_expected.clear()
        self._ap_bt_prev = None   # jamais de franchissement fantôme après resync
        for idx in self._ap_watch_idxs():
            v = _read_slider_pct(self.aw, idx)
            if v is not None:
                self._ap_slider_last[idx] = v

    @pyqtSlot()
    def _ap_toggle(self) -> None:
        """Tap sur la puce : off→armé (gates §6), armé→off, pause→armé."""
        if not _AP_USER_ENABLED:   ## TILAU ## kill-switch : AUTO retiré (2026-07-11)
            return
        now = time.monotonic()
        if self._ap_state == "armed":
            self._ap_set_state("off")
            self._ap_notice = (self._tr_ap_off_note, _S_OK, now + 5)
            return
        if self._ap_state == "paused":
            self._ap_resync()
            self._ap_set_state("armed")
            # Re-baseline le moteur de trim à la reprise : trims cumulés remis à ## TILAU ##
            # zéro et cibles/timing re-lus depuis la position courante — un       ## TILAU ##
            # réglage manuel fait pendant la pause devient la nouvelle référence  ## TILAU ##
            # (sinon le core garde des trims périmés vs les leviers d'avant-pause).## TILAU ##
            # Pas de feedforward : on respecte les sliders tels que laissés.       ## TILAU ##
            _pk = {self._PHASE_MAI: "MAI", self._PHASE_DEV: "DEV"}.get(self._current_phase)
            if _pk is not None:
                self._ap_core_start_phase(_pk)
            self._ap_notice = (self._tr_ap_armed_note, _S_OK, now + 5)
            return
        # off → armement : gates (assistant actif, plan présent, confiance non-low)
        if not self.is_active:
            return
        if self._plan is None:
            self._ap_notice = (self._tr_ap_blocked_noplan, _S_WARN, now + 8)
            return
        support = str(self._plan.get("History Support", "grid only")).lower()
        if support.startswith("grid only"):
            self._ap_notice = (self._tr_ap_blocked_lowconf, _S_WARN, now + 8)
            return
        # ── Flag A/B (QSettings caché, lu à CHAQUE armement off→armé — jamais ── ## TILAU ##
        # au tick) : feedforward-seul + filet minimal vs feedforward + trim v1b.  ## TILAU ##
        # Le mode armé est journalisé pour l'analyse A/B des roasts réels.        ## TILAU ##
        from PyQt6.QtCore import QSettings
        self._ap_ff_only = bool(QSettings().value(_AP_FF_ONLY_KEY, False, type=bool))
        self._ap_resync()
        self._ap_set_state("armed")
        _mode_txt = self._tr_ap_mode_ff if self._ap_ff_only else self._tr_ap_mode_trim
        self._ap_notice = (f"{self._tr_ap_armed_note} · {_mode_txt}", _S_OK, now + 5)
        _logd.info(f"AutoPilot: armed — A/B mode "
                   f"{'feedforward-only' if self._ap_ff_only else 'feedforward+trim'}")
        # feedforward immédiat sur la phase courante (armement en cours de roast)
        _pk = {self._PHASE_DRY: "DRY", self._PHASE_MAI: "MAI",
               self._PHASE_DEV: "DEV"}.get(self._current_phase)
        if _pk is not None:
            self._ap_apply_phase(_pk)
            self._ap_core_start_phase(_pk)   # armement en cours de phase (MAI/DEV)

    def _ap_plan_levers(self, phase_key: str) -> list[tuple[int, float]]:
        """(idx slider, % plan) pour la phase — heater borné à _AP_MAX_BURNER ;
        le slider extraction (2) n'est piloté que si un AirWave est présent ;
        le drum (1) est posé au CHARGE puis VERROUILLÉ sur les machines à
        transition de vitesse brutale (ctx.drum_midroast_locked — Skywalker :
        un saut de 5 % bouleverse l'inertie de la masse, pas de progression)."""
        out: list[tuple[int, float]] = []
        col = _AP_PHASE_COL.get(phase_key)
        if col is None or not self._plan:
            return out
        airwave = getattr(self.aw, "bleAirwaveDevice", None) is not None
        drum_locked = getattr(self.roast_context, "drum_midroast_locked", True)
        # En DEV, si une Dev Ramp existe, air/heater/ext sont portés GRADUELLEMENT ## TILAU ##
        # par la rampe (escalier fin depuis la valeur Maillard) — NE PAS les       ## TILAU ##
        # feedforward ici, sinon saut brutal au FC (bug vu par Tilau 2026-07-10).  ## TILAU ##
        dev_ramp_governs = (phase_key == "DEV" and bool(self._plan.get("Dev Ramp")))
        for idx, key in _AP_LEVER_KEYS.items():
            if idx == 2 and not airwave:
                continue
            if idx == 1 and drum_locked and phase_key != "DRY":
                continue   # drum figé après le CHARGE sur cette machine
            if idx in (0, 2) and dev_ramp_governs:
                continue   # air / ext portés par la Dev Ramp
            try:
                parts = str(self._plan.get(key, "")).split(" | ")
                out.append((idx, float(parts[col].strip().rstrip("%"))))
            except (ValueError, IndexError, TypeError):
                continue
        # Heater : porté par la rampe DÈS LE TP (Heater Ramp en Maillard, Dev Ramp ## TILAU ##
        # en dev) → le feedforward ne le pose QU'au CHARGE (DRY = valeur initiale, ## TILAU ##
        # tenue jusqu'au TP puis descendue progressivement par la rampe). Jamais   ## TILAU ##
        # de saut heater au DE ni au FC.                                           ## TILAU ##
        heater_governed = (dev_ramp_governs
                           or (phase_key == "MAI" and bool(self._plan.get("Heater Ramp"))))
        if not heater_governed:
            h = _plan_heater_pct(self._plan, _AP_PHASE_WORD[phase_key])
            if h is not None:
                out.append((_burner_slider_idx(self.aw), min(h, _AP_MAX_BURNER)))
        return out

    def _ap_apply_phase(self, phase_key: str) -> None:
        """Feedforward au jalon : pose les valeurs de phase du plan (événementiel,
        jamais dans le hot path). Chaque pose passe par le chemin humain, donc
        l'événement Artisan est journalisé et la fenêtre d'inertie coach s'ouvre."""
        if self._ap_state != "armed":
            return
        applied: list[str] = []
        _posed_idx: list[int] = []  ## TILAU ## indices réellement posés dans CET appel (pas tout _ap_expected)
        for idx, pct in self._ap_plan_levers(phase_key):
            cur = _read_slider_pct(self.aw, idx)
            if cur is not None and abs(cur - pct) < 1.0:
                continue
            if _apply_slider_value(self.aw, idx, pct):
                rb = _read_slider_pct(self.aw, idx)
                self._ap_expected[idx] = rb if rb is not None else pct
                _posed_idx.append(idx)
                try:
                    _lbl = str(self.aw.qmc.etypes[idx]).upper()
                except (AttributeError, IndexError):
                    _lbl = f"SLD{idx}"
                applied.append(f"{_lbl} {self._ap_expected[idx]:.0f}%")
        if applied:
            _now = time.monotonic()
            self._ap_notice = (self._tpl_ap_phase.format(phase_key, " · ".join(applied)),
                               _S_OK, _now + 8)
            ## TILAU ## cockpit : carte action + flash des tuiles posées dans CET appel uniquement
            self._ap_last_action = (self._tpl_ap_phase.format(phase_key, " · ".join(applied)), _now)
            for _i in _posed_idx:
                self._ap_lever_flash[_i] = _now
            _logd.info(f"AutoPilot: phase {phase_key} feedforward → {applied}")

    @pyqtSlot()
    def _ap_tile_tapped(self) -> None:
        """Tap sur une tuile levier du cockpit = reprise en main : PAUSE et
        retour aux pages détaillées (quick-adjust ± accessibles). Reprise via
        la puce AUTO."""
        if self._ap_state == "armed":
            self._ap_set_state("paused")
            self._ap_notice = (self._tr_ap_paused_note, _S_WARN, time.monotonic() + 10)
            _logd.info("AutoPilot: lever tile tapped — paused (operator takeover)")

    @pyqtSlot()
    def _ap_ms_clicked(self) -> None:
        """Bouton de jalon du cockpit : marque le jalon de la phase courante ;
        pendant le compte à rebours d'auto-DROP il devient « Annuler » (annule
        le DROP auto, pas le mode AUTO)."""
        if self._current_phase == self._PHASE_DEV and self._ap_drop_deadline is not None:
            self._ap_drop_deadline = None
            self._ap_drop_cancelled = True
            self._ap_last_action = (self._tr_cp_btn_cancel, time.monotonic())
            _logd.info("AutoPilot: auto-DROP cancelled by operator")
            return
        if self._current_phase == self._PHASE_DRY:
            self.aw.qmc.markDRYSignal.emit(False)
        elif self._current_phase == self._PHASE_MAI:
            self.aw.qmc.markFCsSignal.emit(False)
        elif self._current_phase == self._PHASE_DEV:
            self.aw.qmc.markDropSignal.emit(False)

    def _refresh_cockpit(self, ctx: dict, bt: float, ror: "float | None",
                         mode: str, dry_end_temp: float, fc_temp: float,
                         drop_temp: float) -> None:
        """Vue cockpit (v6) — appelée à la place du refresh de page quand AUTO
        pilote. O(1), textes précalculés, aucun texte d'appoint (doctrine v6)."""
        p = self._current_phase
        armed = self._ap_state == "armed"
        pilot = self._tr_cp_pilot if armed else self._tr_cp_paused
        t_now = ctx["t_now_sec"]
        phase_txt = f'· {self._cp_phase_words.get(p, "")} · {int(t_now // 60):d}:{int(t_now % 60):02d}'
        # état — UNE expression, rien dessous
        if not armed:
            status, scol = self._tr_cp_pausest, "#F9E2AF"
        else:
            # v1b : la cible affichée = celle du MOTEUR (droite interpolée par
            # phase, °C) — statut et décisions de trim partagent la même vérité.
            _tgt_c = (self._ap_core.target_ror(float(ctx["t_now_sec"]))
                      if p in (self._PHASE_MAI, self._PHASE_DEV) else None)
            if _tgt_c is not None and _tgt_c > 0 and ror is not None:
                _ror_c = (ror / 1.8) if mode == 'F' else ror
                _d = (_ror_c - _tgt_c) / _tgt_c
                _tol = self._ap_core.p.ok_rel
                if _d > _tol:
                    status, scol = self._tr_cp_drift_h, "#F9E2AF"
                elif _d < -_tol:
                    status, scol = self._tr_cp_drift_l, "#F9E2AF"
                else:
                    status, scol = self._tr_cp_onplan, "#A6E3A1"
            else:
                status, scol = self._tr_cp_follow, "#A6E3A1"
        # action — quoi + quand
        if self._ap_last_action is not None:
            action, _t_act = self._ap_last_action
            _ago = int(time.monotonic() - _t_act)
            when = self._tr_cp_justnow if _ago < 3 else self._tpl_cp_ago.format(_ago)
        else:
            action, when = self._tr_cp_waiting, ""
        # tuiles + flash 10 s
        _now = time.monotonic()
        levers = {i: _read_slider_pct(self.aw, i) for i in (0, 1, 2, 3)}
        flashed = {i for i, t0 in self._ap_lever_flash.items() if _now - t0 < 10.0}
        # barre jalon : progression BT vers la cible de phase + ETA grossier
        if p == self._PHASE_DRY:
            ## Borne basse = le TP du PLAN, en unités natives. Avant, c'était le
            ## champ roaster expected_tp_bt, supprimé le 2026-08-08 : il figeait
            ## un TP « machine » que rien n'étayait. Le plan porte déjà le point,
            ## et le replan TP y écrit le TP RÉELLEMENT observé dès qu'il a lieu —
            ## donc pendant le séchage cette borne est la vraie, pas une théorie.
            _tp_wp = _waypoint(
                ((self._plan or {}).get("bt_plan_curve") or {}).get("waypoints") or [],
                "tp", 1)
            ## Repli inatteignable avec un plan généré (les waypoints existent
            ## toujours) : on dégrade sans jamais diviser par zéro.
            lo = float(_tp_wp["bt"]) if _tp_wp else min(bt, dry_end_temp - 1.0)
            hi = dry_end_temp
        elif p == self._PHASE_MAI:
            lo, hi = dry_end_temp, fc_temp
        else:
            lo, hi = fc_temp, drop_temp
        pct = ((bt - lo) / (hi - lo) * 100.0) if hi > lo else 0.0
        gap = hi - bt
        _ror_s = _ror_smoothed(ror, self._ror_hist) if ror is not None else 0.0
        if gap > 0 and _ror_s > 0.5:
            _eta_s = int(gap / _ror_s * 60.0)
            ms_right = f"~{_eta_s // 60:d}:{_eta_s % 60:02d}"
        else:
            ms_right = f"{hi:.0f}°"
        self._page_cockpit.refresh(armed, pilot, phase_txt, status, scol,
                                   action, when, levers, flashed,
                                   self._cp_ms_words.get(p, ""), pct, ms_right)
        # bouton de jalon : contextualisé par phase, proéminent à l'approche de
        # la cible plan (même convention ±8° que les pages), « Annuler » pendant
        # le compte à rebours d'auto-DROP.
        _btn = self._page_cockpit.btn_ms
        _scale = 1.8 if mode == 'F' else 1.0
        if p == self._PHASE_DEV and self._ap_drop_deadline is not None:
            _label, _style = self._tr_cp_btn_cancel, 'cancel'
        elif p == self._PHASE_DRY:
            _label = self._tr_cp_btn_de
            # garde TP : avant le turning point la BT DESCEND à travers le seuil
            # (température de charge) — sans cette garde le bouton s'allumait dès
            # la charge (même piège que la rampe, franchissement montant requis).
            _style = ('warn' if (ctx["t_tp_sec"] > 0
                                 and (dry_end_temp - bt) <= 8.0 * _scale) else 'dim')
        elif p == self._PHASE_MAI:
            _label = self._tr_cp_btn_fc
            _style = 'warn' if (fc_temp - bt) <= 8.0 * _scale else 'dim'
        else:
            _label = self._tr_cp_btn_drop
            _style = 'warn' if (drop_temp - bt) <= 5.0 * _scale else 'dim'
        if _btn.text() != _label:
            _btn.setText(_label)
        _btn.set_active(True, style=_style)

    def _ap_apply_dev_step(self, step: dict) -> bool:
        """Applique un étage de la rampe de développement (feu ↓, airflow ↑,
        extraction douce ↑). Chemin humain habituel (événement journalisé, écho
        anti-pause). Extraction seulement si un AirWave est présent. Renvoie True
        si au moins un levier a bougé (feedforward prioritaire sur le trim)."""
        _aw_on = getattr(self.aw, "bleAirwaveDevice", None) is not None
        _b_idx = _burner_slider_idx(self.aw)
        _pokes: list[tuple[int, float]] = []
        if "heater" in step:
            _pokes.append((_b_idx, min(float(step["heater"]), _AP_MAX_BURNER)))
        if "airflow" in step:
            _pokes.append((0, float(step["airflow"])))
        if _aw_on and "extraction" in step:
            _pokes.append((2, float(step["extraction"])))
        _acted = False
        _now = time.monotonic()
        _parts: list[str] = []
        for _idx, _val in _pokes:
            _cur = _read_slider_pct(self.aw, _idx)
            if _cur is not None and abs(_cur - _val) >= 1.0 \
                    and _apply_slider_value(self.aw, _idx, _val):
                _rb = _read_slider_pct(self.aw, _idx)
                self._ap_expected[_idx] = _rb if _rb is not None else _val
                self._ap_lever_flash[_idx] = _now
                try:
                    _lbl = str(self.aw.qmc.etypes[_idx]).upper()
                except (AttributeError, IndexError):
                    _lbl = f"SLD{_idx}"
                _parts.append(f"{_lbl} {self._ap_expected[_idx]:.0f}%")
                _acted = True
        if _acted:
            _txt = self._tpl_ap_dev_ramp.format(" · ".join(_parts))
            self._ap_last_action = (_txt, _now)
            self._ap_notice = (_txt, _S_OK, _now + 8)
            _logd.info(f"AutoPilot: dev ramp step → {_parts}")
        return _acted

    def _ap_dev_heater_dispense(self, ctx: dict) -> bool:
        """## TILAU ## « Tenir le feu » (spec §3quater, banc 2026-07-11) : délivre
        la cible feu en file vers le slider burner, MONOTONE (jamais de remontée
        par ce chemin) et rate-limitée dans la fenêtre exotherme FC→FC+75 s
        (≤ _AP_DEV_RATE_PCT_PER_MIN — la coupe rapide crash 41 % vs douce 16 %).
        Un palier BT franchi trop vite est DIFFÉRÉ, jamais sauté. Appelé à chaque
        tick DEV ; O(1). Renvoie True si le feu a bougé (feedforward prioritaire)."""
        _tgt_p = self._ap_dev_heater_pending
        if _tgt_p is None:
            return False
        _b_idx = _burner_slider_idx(self.aw)
        _cur = _read_slider_pct(self.aw, _b_idx)
        if _cur is None:
            return False
        if _cur <= _tgt_p + 0.5:
            self._ap_dev_heater_pending = None   # déjà au niveau (opérateur/plan)
            return False
        _floor = 0.0
        if self._ap_dev_rate_anchor is not None:
            _t0, _b0 = self._ap_dev_rate_anchor
            _t_now = float(ctx.get("t_now_sec", 0.0) or 0.0)
            if _t_now <= _t0 + _AP_DEV_RATE_WINDOW_S:
                # budget de descente linéaire depuis l'entrée en dev
                _floor = max(0.0, _b0 - _AP_DEV_RATE_PCT_PER_MIN * (_t_now - _t0) / 60.0)
        _tgt = min(max(float(_tgt_p), _floor), _AP_MAX_BURNER)
        if _tgt >= _cur:
            return False   # monotone : le budget n'autorise encore aucun pas
        _full = _tgt <= float(_tgt_p) + 1e-6
        # < 2 % = sans effet sur tambour chargé (doctrine) — on attend le budget,
        # sauf pour le dernier pas qui atteint exactement la cible (≥ 1 %).
        if (_cur - _tgt) < (1.0 if _full else 2.0):
            return False
        if not _apply_slider_value(self.aw, _b_idx, _tgt):
            return False
        _rb = _read_slider_pct(self.aw, _b_idx)
        self._ap_expected[_b_idx] = _rb if _rb is not None else _tgt
        _now = time.monotonic()
        self._ap_lever_flash[_b_idx] = _now
        _txt = self._tpl_ap_devfire.format(f"{_tgt:.0f}")
        self._ap_last_action = (_txt, _now)
        self._ap_notice = (_txt, _S_OK, _now + 8)
        if _full:
            self._ap_dev_heater_pending = None
        _logd.info(f"AutoPilot: dev burner rate-limited → {_tgt:.0f}% "
                   f"(pending {_tgt_p:.0f}%, floor {_floor:.0f}%)")
        return True

    def _ap_net_tick(self, crash_msg: "str | None") -> bool:
        """## TILAU ## Filet réactif minimal du dev (spec §3quinquies, décision
        Tilau 2026-07-11 : « agir puis pause si épuisé »). AIR d'abord (l'air
        soutient la réaction — jamais de remontée feu réactive), touches de
        2 %/4-5 s, offset borné _AP_NET_CAP_PCT et AUTO-RÉSORBÉ : quand le RoR
        se repose sur la pente (calme _AP_NET_RESORB_QUIET_S), l'air redescend
        vers le plan par pas de 2 %. Renvoie True = filet ÉPUISÉ (borne atteinte
        et ça crashe toujours) → l'appelant met AUTO en pause."""
        _now = time.monotonic()
        if crash_msg is None:
            if self._ap_net_offset > 0.0:
                if self._ap_net_quiet_since is None:
                    self._ap_net_quiet_since = _now
                elif (_now - self._ap_net_quiet_since >= _AP_NET_RESORB_QUIET_S
                        and _now - self._ap_net_last >= _AP_NET_CADENCE_S):
                    _cur = _read_slider_pct(self.aw, 0)
                    if _cur is not None:
                        _step = min(_AP_NET_STEP_PCT, self._ap_net_offset)
                        _tgt = max(0.0, _cur - _step)
                        if _apply_slider_value(self.aw, 0, _tgt):
                            _rb = _read_slider_pct(self.aw, 0)
                            self._ap_expected[0] = _rb if _rb is not None else _tgt
                            self._ap_net_offset = max(0.0, self._ap_net_offset - _step)
                            self._ap_net_last = _now
                            self._ap_lever_flash[0] = _now
                            _logd.info(f"AutoPilot net: resorb — AIR → {_tgt:.0f}% "
                                       f"(offset {self._ap_net_offset:.0f}%)")
            return False
        # ── crash actif ──
        self._ap_net_quiet_since = None
        if self._ap_net_offset >= _AP_NET_CAP_PCT:
            # borné : on tient encore 2 cadences (l'air agit avec du lag) puis épuisé
            return (_now - self._ap_net_last) >= 2.0 * _AP_NET_CADENCE_S
        if _now - self._ap_net_last >= _AP_NET_CADENCE_S:
            _cur = _read_slider_pct(self.aw, 0)
            if _cur is not None:
                _tgt = min(100.0, _cur + _AP_NET_STEP_PCT)
                if _tgt <= _cur:
                    # air déjà au plafond physique : filet sans munition → épuisé
                    self._ap_net_offset = _AP_NET_CAP_PCT
                    self._ap_net_last = _now
                elif _apply_slider_value(self.aw, 0, _tgt):
                    _rb = _read_slider_pct(self.aw, 0)
                    self._ap_expected[0] = _rb if _rb is not None else _tgt
                    self._ap_net_offset += _AP_NET_STEP_PCT
                    self._ap_net_last = _now
                    self._ap_lever_flash[0] = _now
                    _txt = self._tpl_ap_net.format(f"{_tgt:.0f}")
                    self._ap_last_action = (_txt, _now)
                    self._ap_notice = (crash_msg, _S_WARN, _now + 8)
                    _logd.info(f"AutoPilot net: crash — AIR → {_tgt:.0f}% "
                               f"(offset {self._ap_net_offset:.0f}%)")
        return False

    def _ap_apply_cooling(self) -> None:
        """DROP marqué : pose les réglages de refroidissement (brûleur coupé,
        air/extraction forts, tambour rapide — les grains sont sortis, le verrou
        drum ne s'applique plus), puis désarme : la mission de l'AutoPilot se
        termine au DROP. Événementiel (jamais dans le hot path)."""
        if self._ap_state != "armed":
            return
        airwave = getattr(self.aw, "bleAirwaveDevice", None) is not None
        applied: list[str] = []
        b_idx = _burner_slider_idx(self.aw)
        for idx, pct in _AP_COOLING_LEVERS.items():
            if idx == 2 and not airwave:
                continue
            real_idx = b_idx if idx == 3 else idx
            cur = _read_slider_pct(self.aw, real_idx)
            if cur is not None and abs(cur - pct) < 1.0:
                continue
            if _apply_slider_value(self.aw, real_idx, pct):
                try:
                    _lbl = str(self.aw.qmc.etypes[real_idx]).upper()
                except (AttributeError, IndexError):
                    _lbl = f"SLD{real_idx}"
                applied.append(f"{_lbl} {pct:.0f}%")
        self._ap_set_state("off")
        self._ap_notice = (self._tpl_ap_cool.format(" · ".join(applied) or "--"),
                           _S_OK, time.monotonic() + 12)
        _logd.info(f"AutoPilot: DROP cooling feedforward → {applied} — disarmed")

    def _ap_tick(self, ctx: dict, bt: float, ror: "float | None", mode: str,
                 dry_end_temp: float, fc_temp: float, drop_temp: float) -> None:
        """Appelé à chaque refresh (1 Hz). O(1) : reprise en main → PAUSE,
        crash-guard, palier de rampe dû, puis trim continu (moteur v1b).

        Hors phases de roast (préchauffe notamment), on OBSERVE seulement :
        le PID de préchauffe pilote légitimement le burner (et le fan) — le
        lire comme un geste humain mettait AUTO en pause à tort. La détection
        de reprise en main ne s'arme qu'à partir du CHARGE (couture §3 :
        PID préchauffe off, AutoPilot on)."""
        if self._ap_state != "armed":
            return
        in_roast = self._current_phase in (self._PHASE_DRY, self._PHASE_MAI,
                                           self._PHASE_DEV)
        # ── reprise en main : un changement non attendu = geste humain → PAUSE ──
        for idx in self._ap_watch_idxs():
            v = _read_slider_pct(self.aw, idx)
            if v is None:
                continue
            last = self._ap_slider_last.get(idx)
            self._ap_slider_last[idx] = v
            if not in_roast or last is None or v == last:
                continue   # préchauffe/idle : suivi silencieux, jamais de pause
            exp = self._ap_expected.get(idx)
            if exp is not None and abs(v - exp) <= 0.5:
                self._ap_expected.pop(idx, None)   # écho de notre propre pose
            elif idx == 2 and abs(v - last) < 2.0:
                # dithering ±1 % du PID AirWave sur l'extraction : bruit
                # d'automatisme, pas un geste opérateur (même seuil que Sim-1)
                continue
            elif time.monotonic() < self._ap_charge_settle_until:
                # seam CHARGE : handoff PID préchauffe→roast — mouvement            ## TILAU ##
                # d'automatisme transitoire, pas un geste opérateur. On SUIT        ## TILAU ##
                # (last déjà mis à jour en tête de boucle) sans pauser.             ## TILAU ##
                continue
            else:
                self._ap_set_state("paused")
                self._ap_notice = (self._tr_ap_paused_note, _S_WARN,
                                   time.monotonic() + 10)
                _logd.info(f"AutoPilot: manual input on slider {idx} "
                           f"({last}→{v}) — paused")
                return
        if not in_roast:
            return
        # ── crash-guard : les pages qui alimentaient le détecteur sont masquées ──
        # en cockpit — il DOIT être nourri ici. Prioritaire : pré-empte toute
        # actuation. En DEV (détecteur recalibré banc 2026-07-11), le FILET
        # RÉACTIF minimal agit d'abord (AIR +2 %/4-5 s, borné, auto-résorbé) ;
        # PAUSE seulement s'il est épuisé (décision Tilau 2026-07-11). Hors dev,
        # comportement v1 conservé : crash ⇒ PAUSE.
        _tgt_temp = {self._PHASE_DRY: dry_end_temp, self._PHASE_MAI: fc_temp,
                     self._PHASE_DEV: drop_temp}.get(self._current_phase, drop_temp)
        _net_hold = False   # filet à la main : gèle descente+trim, PAS les jalons
        if ror is not None:
            _in_dev = self._current_phase == self._PHASE_DEV
            _crash = self._crash_detector.check(
                ror, self._ror_hist, bt, target_temp=_tgt_temp,
                dt=max(0.25, self.aw.qmc.delay / 1000.0), dev_mode=_in_dev)
            if _in_dev:
                if self._ap_net_tick(_crash):
                    self._ap_set_state("paused")
                    self._ap_notice = (self._tr_ap_net_exhausted, _S_WARN,
                                       time.monotonic() + 12)
                    _logd.info("AutoPilot: crash net exhausted — paused")
                    return
                # pendant un crash : plus aucune baisse de feu ni trim, mais les
                # jalons et l'auto-DROP CONTINUENT (BT à la cible ⇒ dropper,
                # surtout en crash — sinon sur-cuisson pendant que le filet agit)
                _net_hold = _crash is not None
            elif _crash:
                self._ap_set_state("paused")
                self._ap_notice = (_crash, _S_WARN, time.monotonic() + 10)
                _logd.info("AutoPilot: RoR crash detected — paused")
                return
        # ── jalons : AUTO armé ⇒ une suggestion fraîche du détecteur est       ──
        # marquée automatiquement (spec §4 — le cockpit n'a pas de bouton de
        # confirmation ; les boutons Artisan restent le repli manuel).
        _which = {self._PHASE_DRY: "DE", self._PHASE_MAI: "FC"}.get(self._current_phase)
        if _which is not None and _which not in self._ap_automark_done:
            _sug = _milestone_suggestion(self.aw, _which)
            if _sug is not None:
                self._ap_automark_done.add(_which)
                if _which == "DE":
                    self.aw.qmc.markDRYSignal.emit(False)
                else:
                    self.aw.qmc.markFCsSignal.emit(False)
                _now = time.monotonic()
                _txt = self._tpl_ap_marked.format("DRY END" if _which == "DE" else "FC START")
                self._ap_last_action = (_txt, _now)
                self._ap_notice = (_txt, _S_OK, _now + 8)
                _logd.info(f"AutoPilot: milestone {_which} auto-marked")
                return
        # ── auto-DROP plan (v1c, validé : 10 s annulables) : en DEV, quand la  ──
        # BT atteint la cible de drop du plan vivant, compte à rebours 10 s
        # affiché dans la carte action + bouton « Annuler » ; au terme, DROP
        # marqué. One-shot : annulé = plus jamais re-armé cette session.
        if self._current_phase == self._PHASE_DEV and not self._ap_drop_cancelled:
            _now = time.monotonic()
            if self._ap_drop_deadline is None:
                try:
                    _drop_t = float((self._plan or {}).get("Drop Temp") or 0.0)
                except (TypeError, ValueError):
                    _drop_t = 0.0
                if _drop_t > 0 and bt >= _drop_t:
                    self._ap_drop_deadline = _now + 10.0
                    QApplication.beep()
                    _logd.info(f"AutoPilot: plan drop target {_drop_t:.1f}° reached "
                               f"— auto-DROP countdown")
            if self._ap_drop_deadline is not None:
                _left = self._ap_drop_deadline - _now
                if _left <= 0:
                    self._ap_drop_deadline = None
                    self._ap_drop_cancelled = True   # one-shot
                    self._ap_last_action = (self._tr_ap_dropmark, _now)
                    self.aw.qmc.markDropSignal.emit(False)
                    _logd.info("AutoPilot: DROP auto-marked")
                else:
                    self._ap_last_action = (self._tpl_ap_dropin.format(int(_left) + 1), _now)
        # ── rampe heater BT-keyed : palier appliqué au FRANCHISSEMENT MONTANT ──
        # du seuil uniquement (bt_prev < seuil <= bt). La descente pré-TP du
        # CHARGE ne déclenche donc jamais rien ; le heater de séchage vient du
        # feedforward de phase, la rampe ne fait que le baisser plus tard.
        ramp_acted = False
        # _ap_bt_prev est maintenu sur DRY/MAI/DEV (continuité du franchissement) ; ## TILAU ##
        # remis à None hors phase de roast.                                        ## TILAU ##
        prev = self._ap_bt_prev
        self._ap_bt_prev = bt
        if self._current_phase in (self._PHASE_DRY, self._PHASE_MAI):
            hit = _ap_ramp_crossed(self._plan, prev, bt) if prev is not None else None
            if hit is not None:
                thr, heater = hit
                heater = min(float(heater), _AP_MAX_BURNER)
                b_idx = _burner_slider_idx(self.aw)
                cur = _read_slider_pct(self.aw, b_idx)
                if cur is not None and abs(cur - heater) >= 1.0 \
                        and _apply_slider_value(self.aw, b_idx, heater):
                    rb = _read_slider_pct(self.aw, b_idx)
                    self._ap_expected[b_idx] = rb if rb is not None else heater
                    _now = time.monotonic()
                    _txt = self._tpl_ap_ramp.format(f"{heater:.0f}", f"{thr:.0f}")
                    self._ap_notice = (_txt, _S_OK, _now + 8)
                    self._ap_last_action = (_txt, _now)      ## TILAU ## cockpit
                    self._ap_lever_flash[b_idx] = _now       ## TILAU ## cockpit
                    ramp_acted = True   # feedforward prioritaire : pas de trim ce tick
                    _logd.info(f"AutoPilot: ramp step crossed at BT {thr:.0f} "
                               f"→ burner {heater:.0f}%")
            # ── rampe AIRFLOW de Maillard (montée douce pour chasser les fumées) ──
            if self._current_phase == self._PHASE_MAI and prev is not None:
                _ahit = _ap_entry_ramp_crossed(self._plan, "Air Ramp", prev, bt)
                if _ahit is not None and self._ap_apply_dev_step(_ahit):
                    ramp_acted = True
        # ── rampe de DÉVELOPPEMENT (trajectoire apprise) : feu qui baisse +      ──
        # airflow qui monte + extraction douce, appliqués au franchissement       ──
        # montant des seuils BT. Stoppée dès que le compte à rebours DROP s'arme.  ──
        # « TENIR LE FEU » (spec §3quater) : le burner n'est JAMAIS posé direct — ──
        # mis en FILE (monotone : cible la plus basse gagne, jamais de remontée)  ──
        # et délivré par le dispenser rate-limité (≤ 5 %/min en fenêtre           ──
        # exotherme FC→FC+75 s — la coupe rapide = ÷2,5 de risque de crash).      ──
        elif (self._current_phase == self._PHASE_DEV
              and self._ap_drop_deadline is None and not _net_hold):
            if prev is not None:
                _dhit = _ap_entry_ramp_crossed(self._plan, "Dev Ramp", prev, bt)
                if _dhit is not None:
                    _dhit = {k: v for k, v in _dhit.items() if k not in ("bt", "_f")}
                    _h = _dhit.pop("heater", None)
                    if _h is not None:
                        _p = self._ap_dev_heater_pending
                        self._ap_dev_heater_pending = (float(_h) if _p is None
                                                       else min(_p, float(_h)))
                    if _dhit:
                        ramp_acted = self._ap_apply_dev_step(_dhit)
            if not ramp_acted:
                ramp_acted = self._ap_dev_heater_dispense(ctx)

        # ── trim continu (v1b, moteur autopilot_core calé Sim-1/Sim-2) ────────
        # MAI + DEV seulement (périmètre des sims) ; max 1 actuation par tick :
        # si la rampe a agi, le moteur observe mais n'agit pas ce tour-ci.
        # Flag A/B : en mode feedforward-seul le moteur est ENTIÈREMENT sauté
        # (ni observation ni action — le filet réactif est la seule réaction).
        if (not self._ap_ff_only and not _net_hold
                and self._current_phase in (self._PHASE_MAI, self._PHASE_DEV)
                and not ramp_acted and ror is not None
                and self._ap_drop_deadline is None):   # drop imminent → on ne trime plus
            _aw_on = getattr(self.aw, "bleAirwaveDevice", None) is not None
            _b_idx = _burner_slider_idx(self.aw)
            self._ap_core.observe_levers(
                air=_read_slider_pct(self.aw, 0),
                heater=_read_slider_pct(self.aw, _b_idx),
                ext=_read_slider_pct(self.aw, 2) if _aw_on else None)
            _ror_c = (ror / 1.8) if mode == 'F' else ror
            _act = self._ap_core.tick(float(ctx["t_now_sec"]), _ror_c)
            # AirWave déconnecté en cours de roast : le core peut encore émettre  ## TILAU ##
            # une action EXT sur une valeur observée périmée — ne jamais la poser ## TILAU ##
            # sur le slider 2 sans AirWave présent (les chemins feedforward sont  ## TILAU ##
            # déjà gardés de la même façon).                                       ## TILAU ##
            if _act is not None and _act.lever is _APLever.EXT and not _aw_on:
                _act = None
            if _act is not None:
                _idx = {_APLever.AIR: 0, _APLever.HEATER: _b_idx,
                        _APLever.EXT: 2}[_act.lever]
                if _apply_slider_value(self.aw, _idx, _act.target_value):
                    _rb = _read_slider_pct(self.aw, _idx)
                    self._ap_expected[_idx] = _rb if _rb is not None else _act.target_value
                    _now = time.monotonic()
                    try:
                        _lbl = str(self.aw.qmc.etypes[_idx]).upper()
                    except (AttributeError, IndexError):
                        _lbl = f"SLD{_idx}"
                    _txt = self._tpl_ap_trim.format(
                        _lbl, f"{_act.target_value:.0f}", _act.reason)
                    self._ap_last_action = (_txt, _now)
                    self._ap_lever_flash[_idx] = _now
                    self._ap_notice = (_txt, _S_OK, _now + 8)
                    _logd.info(f"AutoPilot trim: {_act.lever.value} "
                               f"{_act.delta_pct:+.1f}% ({_act.kind} · {_act.reason})")
            elif self._ap_core.bound_hit is not None:
                # borne atteinte = le plan est probablement faux — le dire UNE fois
                self._ap_core.bound_hit = None
                self._ap_notice = (self._tr_ap_ceiling, _S_WARN, time.monotonic() + 8)

    def _refresh_current_page(self) -> None:
        """## TILAU ## Garde du slot bridge : AUCUNE exception d'un refresh de page
        (par tick) ne doit s'échapper dans le slot PyQt6 — elle remonterait en
        unraisable-hook et pourrait faire planter l'app EN PLEIN ROAST. Même
        contrat défensif que `_ap_tick`. On journalise la trace et on continue."""
        try:
            self._refresh_current_page_impl()
        except Exception:  # pylint: disable=broad-except
            _logd.exception("RoastAssistant: _refresh_current_page failed (tick skipped)")

    def _refresh_current_page_impl(self) -> None:
        """
        Point central de rafraîchissement — appelé une fois par cycle BT.
        Collecte le contexte qmc une seule fois, dispatche à la bonne page.
        """
        if not self.is_active or self._current_phase == self._PHASE_IDLE:
            return

        ctx = self._collect_qmc_context()
        bt      = ctx["bt"]
        et      = ctx["et"]
        ror     = ctx["ror"]
        mode    = ctx["mode"]
        phases  = ctx["phases"]
        ti      = ctx["ti"]

        # Surveillance burner (opérateur OU alarme de rampe) : tout changement  ## TILAU ##
        # du slider ouvre la fenêtre d'inertie lue par le conseil RoR.          ## TILAU ##
        try:                                                                    ## TILAU ##
            _b = _read_slider_pct(self.aw, _burner_slider_idx(self.aw))         ## TILAU ##
            if _b is not None:                                                  ## TILAU ##
                if self._burner_last_pct is not None and _b != self._burner_last_pct:
                    self.aw._tilau_burner_watch = {
                        "t": time.monotonic(), "from": self._burner_last_pct,
                        "to": _b, "lag": self._heater_lag_s, "dev0": None,
                    }
                    _logd.info(f"RoastAssistant: burner {self._burner_last_pct}→{_b}% "
                               f"— coach hold {self._heater_lag_s:.0f}s")
                self._burner_last_pct = _b
        except Exception:  # pylint: disable=broad-except                       ## TILAU ##
            pass                                                                ## TILAU ##

        # Watch tambour : un geste drum pollue la MESURE du RoR (excursion      ## TILAU ##
        # +50 % médiane, 64/81 roasts) — le détecteur de crash est muet         ## TILAU ##
        # DRUM_QUIET_S après tout mouvement (opérateur, alarme ou AUTO).        ## TILAU ##
        try:                                                                    ## TILAU ##
            _d = _read_slider_pct(self.aw, 1)                                   ## TILAU ##
            if _d is not None:                                                  ## TILAU ##
                if self._drum_last_pct is not None and _d != self._drum_last_pct:
                    self._crash_detector.notify_drum_event()                    ## TILAU ##
                    _logd.info(f"RoastAssistant: drum {self._drum_last_pct}→{_d}% "
                               f"— RoR crash detection muted "
                               f"{_RoRCrashDetector.DRUM_QUIET_S:.0f}s")
                self._drum_last_pct = _d                                        ## TILAU ##
        except Exception:  # pylint: disable=broad-except                       ## TILAU ##
            pass                                                                ## TILAU ##

        # Recalage TP one-shot : dès que le TP réel est détecté, l'ancre TP     ## TILAU ##
        # modélisée est remplacée par la mesure (le delta plan devient fiable   ## TILAU ##
        # dès la 1ʳᵉ minute). Garde O(1) — une seule tentative par session.     ## TILAU ##
        if (self._plan is not None and "tp" not in self._replan_attempted       ## TILAU ##
                and ctx["t_tp_sec"] > 0):                                       ## TILAU ##
            self._replan_attempted.add("tp")                                    ## TILAU ##
            try:                                                                ## TILAU ##
                _tp_idx = int(getattr(self.aw.qmc, "TPalarmtimeindex", -1) or -1)  ## TILAU ##
                if 0 < _tp_idx < len(self.aw.qmc.temp2):                        ## TILAU ##
                    _bt_tp = float(self.aw.qmc.temp2[_tp_idx])                  ## TILAU ##
                    if _bt_tp > 0:                                              ## TILAU ##
                        self._apply_replan("tp", ctx["t_tp_sec"] / 60.0, _bt_tp)  ## TILAU ##
            except Exception:  # pylint: disable=broad-except                   ## TILAU ##
                pass                                                            ## TILAU ##

        # Températures cibles (plan en priorité, sinon phases Artisan, sinon défaut)
        _def_dry  = 160.0 if mode == 'C' else fromCtoFstrict(160.0)
        _def_fc   = 196.0 if mode == 'C' else fromCtoFstrict(196.0)
        _def_drop = 210.0 if mode == 'C' else fromCtoFstrict(210.0)

        dry_end_temp = float(phases[1]) if len(phases) > 1 else _def_dry
        fc_temp      = float(phases[2]) if len(phases) > 2 else _def_fc
        drop_temp    = float(phases[3]) if len(phases) > 3 else _def_drop

        if self._plan:
            try:
                dry_end_temp = float(self._plan.get("End of Dry Temp",   dry_end_temp))
                fc_temp      = float(self._plan.get("First Crack Temp",  fc_temp))
                drop_temp    = float(self._plan.get("Drop Temp",         drop_temp))
            except (TypeError, ValueError):
                pass

        # AutoPilot : reprise en main, crash-guard, rampe, trim continu (v1b).  ## TILAU ##
        # APRÈS le calcul des températures cibles (le crash-guard en a besoin), ## TILAU ##
        # gardé (armé seulement) — jamais de charge quand AUTO est off.         ## TILAU ##
        if self._ap_state == "armed":                                           ## TILAU ##
            try:                                                                ## TILAU ##
                self._ap_tick(ctx, bt, ror, mode,                               ## TILAU ##
                              dry_end_temp, fc_temp, drop_temp)                 ## TILAU ##
            except Exception:  # pylint: disable=broad-except                   ## TILAU ##
                pass                                                            ## TILAU ##

        if self._ap_cockpit_active():                                           ## TILAU ##
            # AUTO pilote : la vue cockpit remplace la page de phase (v6) —     ## TILAU ##
            # quatre éléments, gros, pas de détail. Les pages restent la vue    ## TILAU ##
            # manuel/guidé.                                                     ## TILAU ##
            self._refresh_cockpit(ctx, bt, ror, mode,                           ## TILAU ##
                                  dry_end_temp, fc_temp, drop_temp)             ## TILAU ##

        elif self._current_phase == self._PHASE_PREHEAT:
            self._refresh_preheat(ctx)

        elif self._current_phase == self._PHASE_DRY:
            self._page_dry._advisor_tips = self._advisor_tips_for(self._current_phase)
            self._page_dry.refresh(
                bt=bt, et=et, ror=ror, ror_hist=self._ror_hist,
                phases=phases, dry_end_temp=dry_end_temp, mode=mode,
                bean=self._bean, plan=self._plan,
                t_now_sec=ctx["t_now_sec"],
                t_tp_sec=ctx["t_tp_sec"],
                crash_detector=self._crash_detector,
            )

        elif self._current_phase == self._PHASE_MAI:
            self._page_mai.refresh(
                bt=bt, ror=ror, ror_hist=self._ror_hist,
                t_charge_sec=0.0,
                t_dryend_sec=ctx["t_dryend_sec"],
                t_now_sec=ctx["t_now_sec"],
                fc_temp=fc_temp, plan=self._plan, bean=self._bean,
                mode=mode,
                crash_detector=self._crash_detector,
            )

        elif self._current_phase == self._PHASE_DEV:
            self._page_dev.refresh(
                bt=bt, ror=ror, ror_hist=self._ror_hist,
                bt_at_fcs=self._bt_at_fcs,
                t_charge_sec=0.0, t_fcs_sec=ctx["t_fcs_sec"],
                t_now_sec=ctx["t_now_sec"],
                drop_temp=drop_temp, plan=self._plan,
                agtron_target=self._agtron,
                mode=mode,
                c0=self._c0, c_bt=self._c_bt,
                c_dtr=self._c_dtr, c_wl=self._c_wl,
                crash_detector=self._crash_detector,
            )

        elif self._current_phase == self._PHASE_DROP:
            # Couleur prédite pour le résumé (même modèle que DevPage), FIGÉE
            # aux valeurs du DROP : pendant le refroidissement, t_now avance
            # (le DTR gonflerait) et la BT chute (le terme c_bt × BT ferait
            # dériver la prédiction de ~1,5 pt Agtron par °C perdu). Le résumé
            # doit décrire le roast, pas le refroidissement.
            _agtron_pred_cooling: float | None = None
            try:
                _t_drop = ctx["t_drop_sec"]
                if _t_drop > 0:
                    _bt_ref = float(self.aw.qmc.temp2[ti[6]])
                    _t_ref  = _t_drop
                else:  # DROP pas encore marqué (arrivée anticipée sur la page)
                    _bt_ref = bt
                    _t_ref  = ctx["t_now_sec"]
                dtr = _dtr_realtime(_t_ref, 0.0, ctx["t_fcs_sec"])
                if dtr is not None:
                    # Coefficients calibrés en °C — convertir la BT en mode °F
                    _bt_ref_c = fromFtoCstrict(_bt_ref) if mode == 'F' else _bt_ref
                    _agtron_pred_cooling = max(20.0, min(130.0,
                        self._c0 + self._c_bt * _bt_ref_c + self._c_dtr * dtr + self._c_wl * 14.0
                    ))
            except Exception:
                pass
            self._page_drop.refresh(
                bt=bt, et=et, ror=ror,
                ror_hist=self._ror_hist,
                next_batch_planned=self.aw.qmc.batchcounter > -1,
                # Bilan EOR sur le plan INITIAL figé : l'adhérence doit se       ## TILAU ##
                # mesurer contre la prédiction de départ, pas contre le plan    ## TILAU ##
                # vivant re-ancré (trivialement bon par construction).          ## TILAU ##
                plan=self._plan_initial or self._plan,                          ## TILAU ##
                agtron_target=self._agtron,
                agtron_pred=_agtron_pred_cooling,
            )

        # AutoPilot : quand AUTO est armé, le bouton one-tap « Set burner » est  ## TILAU ##
        # masqué — l'AutoPilot exécute la rampe, le bouton ferait doublon (§5). ## TILAU ##
        if self._ap_state == "armed" and self._current_phase == self._PHASE_MAI:  ## TILAU ##
            try:                                                                ## TILAU ##
                self._page_mai.btn_ramp.setVisible(False)                       ## TILAU ##
            except (AttributeError, RuntimeError):                              ## TILAU ##
                pass                                                            ## TILAU ##

        # Suggestion de jalon (#10) : quand le détecteur repère DRY END / FC,
        # bandeau de confirmation one-tap + bouton proéminent + bip unique. Le
        # marquage reste manuel (tap sur le bouton) sauf auto-mark opt-in.
        self._handle_milestone_suggestion()

        # Voix de l'AutoPilot (§5 : pas de bannière — la ligne coach rend       ## TILAU ##
        # compte) puis notice de recalage : informatives, elles ne masquent     ## TILAU ##
        # jamais un message warn/crit posé par la page pendant ce tick.         ## TILAU ##
        _painted_ap = False                                                     ## TILAU ##
        if self._ap_notice is not None:                                         ## TILAU ##
            _text, _level, _expiry = self._ap_notice                            ## TILAU ##
            if time.monotonic() > _expiry:                                      ## TILAU ##
                self._ap_notice = None                                          ## TILAU ##
            else:                                                               ## TILAU ##
                _coach = getattr(self._stack.currentWidget(), "coach", None)    ## TILAU ##
                if _coach is not None and (_level == _S_WARN                    ## TILAU ##
                        or getattr(_coach, "_level", _S_OK) == _S_OK):          ## TILAU ##
                    _coach.set(_text, _level)                                   ## TILAU ##
                    _painted_ap = True                                          ## TILAU ##
        if not _painted_ap and self._replan_notice is not None:                 ## TILAU ##
            _text, _level, _expiry = self._replan_notice                        ## TILAU ##
            if time.monotonic() > _expiry:                                      ## TILAU ##
                self._replan_notice = None                                      ## TILAU ##
            else:                                                               ## TILAU ##
                _coach = getattr(self._stack.currentWidget(), "coach", None)    ## TILAU ##
                if _coach is not None and getattr(_coach, "_level", _S_OK) == _S_OK:  ## TILAU ##
                    _coach.set(_text, _level)                                   ## TILAU ##

        # Recalcule la taille si nécessaire (contenu dynamique : banner, boutons)
        self._adjust_size_if_needed()

    def _handle_milestone_suggestion(self) -> None:
        """Bandeau « jalon détecté — confirmer ? » (#10). Centralisé : rend le
        bouton de marquage proéminent (style cancel/rouge), pose un prompt coach
        prioritaire (sans écraser un crit déjà posé) et bipe UNE fois par
        suggestion. Le marquage lui-même reste le clic sur le bouton (câblé)."""
        if self._ap_cockpit_active():
            return   ## TILAU ## en cockpit AUTO, le marquage est automatique (_ap_tick)
        try:
            if self._current_phase == self._PHASE_DRY:
                which, page, btn = "DE", self._page_dry, self._page_dry.btn_dry_end
                prompt = self._tr_confirm_de
            elif self._current_phase == self._PHASE_MAI:
                which, page, btn = "FC", self._page_mai, self._page_mai.btn_fcs
                prompt = self._tr_confirm_fc
            else:
                return
            # Mémorise le texte par défaut du bouton pour le restaurer après
            # expiration (la page ne réécrit que le style, jamais le texte).
            if not hasattr(btn, "_tilau_default_text"):
                btn._tilau_default_text = btn.text()
            sug = _milestone_suggestion(self.aw, which)
            if sug is None:
                if btn.text() != btn._tilau_default_text:
                    btn.setText(btn._tilau_default_text)
                return
            # Bouton proéminent + toujours cliquable (le tap marque le jalon).
            btn.set_active(True, style='cancel')
            btn.setText(prompt)
            # Bip unique par suggestion (clé = timestamp monotone publié).
            _t = float(sug.get("t_mono", 0.0))
            if self._last_milestone_beep_t != _t:
                QApplication.beep()
                self._last_milestone_beep_t = _t
            # Prompt coach prioritaire, sauf si la page a déjà posé un crit.
            coach = getattr(page, "coach", None)
            if coach is not None and getattr(coach, "_level", _S_OK) != _S_CRIT:
                coach.set(prompt, _S_WARN)
        except Exception as e:  # pylint: disable=broad-except
            _logd.debug(f"milestone suggestion handling failed: {e}")

    def _refresh_preheat(self, ctx: dict) -> None:
        """Refresh dédié preheat — extrait pour lisibilité."""
        bt   = ctx["bt"]
        et   = ctx["et"]
        ror  = ctx["ror"]
        mode = ctx["mode"]

        pid_active = False
        sv = float(self.aw.pidcontrol.sv or 0)
        try:
            tpid = getattr(self.aw, "tilauPreheatingPid", None)
            if tpid and tpid.active:
                pid_active = True
                # cfg.target_sv est stocké en °C interne — l'accesseur rend
                # l'unité d'affichage (la page traite sv comme natif).
                sv = tpid.sv_native()
            elif self.aw.pidcontrol.pidActive:
                pid_active = True
                sv = float(self.aw.pidcontrol.sv)
        except Exception:
            pass

        heater_pct = 0
        try:
            tpid = getattr(self.aw, "tilauPreheatingPid", None)
            slider_idx = getattr(tpid, "cfg", None) and tpid.cfg.heater_slider or 3
            heater_pct = int(
                self.aw.tilauscope_main.sld_list[slider_idx].value()
                if hasattr(self.aw, "tilauscope_main") else 0
            )
        except Exception:
            pass

        phases  = ctx["phases"]
        _def_charge = float(phases[0]) if phases else (185.0 if mode == 'C' else fromCtoFstrict(185.0))
        charge_temp = float(self._plan.get("Charge Temp", _def_charge)) if self._plan else _def_charge

        self._page_preheat.refresh(
            bt=bt, et=et, ror=ror, ror_hist=self._ror_hist,
            mode=mode, pid_active=pid_active, sv=sv,
            heater_pct=heater_pct, charge_temp=charge_temp,
            soak_note=self._soak_note,
        )
        # Rafraîchit les valeurs des boutons quick adjust
        self._page_preheat.quick_adjust.refresh()

    # ── Compatibilité descendante (appelé si bridge non connecté) ─────────────

    def on_artisan_update(self, data: int | str, value) -> None:
        """
        Kept for backward compatibility if bridge is not connected.
        Appeler connect_bridge() pour migrer vers le mode signaux.
        """
        if not self.is_active or self._current_phase == self._PHASE_IDLE:
            return

        qmc = self.aw.qmc
        ror = None
        bt = et = 0.0
        try:
            bt  = float(qmc.temp2[-1])
            et  = float(qmc.temp1[-1])
            ror = float(qmc.delta2[-1] if qmc.delta2 else 0.0)
            self._ror_hist.append(ror)
        except (IndexError, TypeError, AttributeError):
            pass


        # Backward compat: forward to the new unified refresh path
        if bt != 0.0:
            self._last_bt = bt
        if et != 0.0:
            self._last_et = et
        if ror is not None:
            self._last_ror = ror
        if data == 10:
            self._refresh_current_page()

    def _average_color_in_agtron(self, color: float, color_system: str) -> float:
        """Convert a color reading to the Agtron scale via the single shared
        converter (tilauscope_types.to_agtron) so every module agrees."""
        return to_agtron(color, color_system)

    def populate_bean_list(self) -> None:
        """
        Charge la liste des grains depuis BeanHelper et pré-sélectionne
        le grain courant via l'UUID extrait du champ beans d'Artisan.
        Doit être appelé avant chaque affichage du panel (show()).

        La dropdown est toujours remplie même sans profil chargé.
        L'UUID courant et la couleur cible sont extraits opportunistiquement
        depuis le profil de fond ou le simulateur si disponibles.
        """
        # ── 1. Load beans — mandatory, abort only here ─────────────────────────
        try:
            from tilauscope.beancave import load_cave_beans
            beans = load_cave_beans()
        except Exception as e:
            _logd.warning(f"RoastAssistant: cannot load beans ({e})")
            return

        # Only offer beans that are actually in stock (weight_left > 0), EXCEPT
        # in simulator mode where every bean must stay selectable for testing
        # (replaying any past roast, regardless of remaining stock). ## TILAU ##
        #
        # The bean pushed by RoastSetup (uuid carried by qmc.beans) is ALWAYS
        # kept, even at zero stock: roasting the bottom of the bag drops the
        # stock to 0 and the grain would otherwise vanish from its own roast.
        if self.aw.simulator is None:
            live_uuid: str | None = None
            try:
                live_uuid = _extract_uuid_from_beans_field(
                    getattr(self.aw.qmc, "beans", "") or "")
            except Exception as e:  # noqa: BLE001
                _logd.debug(f"RoastAssistant: erreur lecture qmc.beans ({e})")
            beans = [
                b for b in beans
                if (getattr(b, "weight_left", 0.0) or 0.0) > 0
                or (live_uuid and getattr(b, "uuid", "") == live_uuid)
            ]

        if not beans:
            _logd.debug("RoastAssistant: aucun grain trouvé dans BeanCave")
            self._setup_bar.populate_beans([], None, None)
            self._refresh_bean_header()
            return

        # ── 2. UUID courant — priorité (Tilau 2026-07-11 : la sélection LIVE     ## TILAU ##
        # prime sur un background resté chargé ; sinon un vieux profil de fond    ## TILAU ##
        # 74110 écrasait la sélection live Kojoyo, plan/grain affichés faux) :    ## TILAU ##
        #   1. simulateur (replay) → profil simulé fait foi                       ## TILAU ##
        #   2. sélection LIVE (qmc.beans) si elle porte un UUID valide            ## TILAU ##
        #   3. background profile (roast chargé pour comparaison) — repli SEUL.   ## TILAU ##
        current_uuid: str | None = None
        profile_path: dict | None = None
        try:
            if self.aw.simulator is not None and hasattr(self.aw.simulator, "profile"):
                profile_path = self.aw.simulator.profile   # replay : le profil simulé fait foi
        except Exception as e:
            _logd.debug(f"RoastAssistant: impossible d'accéder au simulateur ({e})")

        if profile_path is not None:
            try:
                current_uuid = _extract_uuid_from_beans_field(profile_path.get("beans") or "")
            except Exception as e:
                _logd.debug(f"RoastAssistant: erreur lecture beans du profil simulé ({e})")
        else:
            # Sélection live d'abord — un roast en cours de setup ne doit jamais
            # être écrasé par un background resté chargé.
            try:
                current_uuid = _extract_uuid_from_beans_field(getattr(self.aw.qmc, "beans", "") or "")
            except Exception as e:
                _logd.debug(f"RoastAssistant: erreur lecture qmc.beans ({e})")
            # Background SEULEMENT si la session live ne porte aucun UUID.
            if current_uuid is None:
                try:
                    _bg = self.aw.qmc.backgroundprofile
                    if _bg is not None:
                        profile_path = _bg
                        current_uuid = _extract_uuid_from_beans_field(_bg.get("beans") or "")
                except Exception as e:
                    _logd.debug(f"RoastAssistant: erreur lecture background ({e})")

        # ── 3. Couleur cible ─────────────────────────────────────────────────────
        # Live (profile_path None) : la CIBLE du RoastSetup prime (Tilau 2026-07-11 :
        # sinon le combo restait collé sur Medium Dark au lieu de suivre Light).
        # Sim/background : couleur extraite du profil.
        ag_color: float | None = None

        if profile_path is not None:
            try:
                ground       = profile_path.get("ground_color", 0) or 0
                whole        = profile_path.get("whole_color",  0) or 0
                color_system = profile_path.get("color_system", "Agtron") or "Agtron"
                raw_color    = ground if ground > 0 else (whole if whole > 0 else 0)
                if raw_color > 0:
                    ag_color = self._average_color_in_agtron(
                        float(raw_color),
                        self.aw.qmc.color_systems[self.aw.qmc.color_system_idx]
                        if color_system == "Agtron" else color_system,
                    )
            except Exception as e:
                _logd.debug(f"RoastAssistant: erreur lecture couleur profil ({e})")
        else:
            _lt = getattr(self.aw, "_tilau_live_target", None)   ## TILAU ## cible RoastSetup
            if _lt is not None:
                try:
                    ag_color = (_lt.agtron_range.min_value + _lt.agtron_range.max_value) / 2.0
                except Exception as e:  # noqa: BLE001
                    _logd.debug(f"RoastAssistant: erreur lecture cible live ({e})")

        # ── 4. Remplir la dropdown — toujours, même sans profil ──────────────────
        self._setup_bar.populate_beans(beans, current_uuid, ag_color)
        ## TILAU ## populate_beans() fills the combo with signals blocked, so the
        ## header has to be refreshed explicitly here.
        self._refresh_bean_header()
        _logd.debug(
            f"RoastAssistant: {len(beans)} grain(s) chargé(s), "
            f"uuid={current_uuid!r}, ag_color={ag_color}"
        )

# ── Visibilité du panel, cacher le panneau par le bouton ────────────────────────────────────────────────────
    def hide_from_button(self):
        self._stop_assistant()
        self.hide()
        self.closed.emit()   ## TILAU ## host re-syncs open/close state

    def toggle_visibility(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.populate_bean_list()
            self.show()
            self.raise_()

    def auto_start_from_workflow(self) -> None:
        """Démarre l'assistant sans interaction utilisateur depuis le workflow guidé.

        Prérequis : populate_bean_list() a déjà identifié le grain et l'Agtron cible.
        Sans-op si l'assistant est déjà actif ou si le grain/cible est absent.
        """
        if self.is_active:
            return
        if self._setup_bar.selected_bean() is None or self._setup_bar.selected_agtron() is None:
            return
        self._bean_header.btn_toggle.setChecked(True)
        self._start_assistant()

    # ── Anchoring support ## TILAU ## ──────────────────────────────────────────

    def take_body(self) -> QWidget:
        """Return the assistant body so an external host can embed it.

        Reparenting is performed by the caller (e.g. QScrollArea.setWidget).
        All bridge/signal connections live on child widgets and are preserved
        across the move, so roast state survives an anchor/float transition.
        """
        self._body_detached = True   ## TILAU ## host now owns sizing — skip shell resize
        return self._body

    def give_body(self) -> None:
        """Re-attach the body into this floating shell's layout."""
        self._inner.addWidget(self._body, 1)
        self._body_detached = False  ## TILAU ## shell owns sizing again

class RoasterPhysicsAdvisor:
    def __init__(self, roaster_ctx:RoasterContext):
        self.ctx:RoasterContext|None = roaster_ctx

    def get_phase_advice(self, phase: int, current_metrics: dict) -> list[str]:
        if self.ctx is None:
            return []
        advice: list[str] = []

        # Map phase integer constants → string labels used for comparison
        _PHASE_LABEL = {1: "DRY", 2: "MAILLARD", 3: "DEVELOPMENT", 4: "PREHEAT", 5: "COOLING"}
        phase_label = _PHASE_LABEL.get(phase, "")

        # General Machine Characteristics
        if self.ctx.airflow_dependency_index > 0.75:
            advice.append(QApplication.translate("tilauscope_roast_assistant", "Sensitive Airflow: use small ±5% increments to avoid BT crashes."))

        if self.ctx.is_radiant_electric:
            advice.append(QApplication.translate("tilauscope_roast_assistant", "Radiant Heat: Proactive power-down needed 15°C before FC."))

        # Phase-Specific Logic
        if phase_label == "MAILLARD":
            if self.ctx.thermal_mass_index > 0.6:
                advice.append(QApplication.translate("tilauscope_roast_assistant", "High Thermal Mass: Step down heater now to control FC entry."))

        elif phase_label == "DEVELOPMENT":
            if self.ctx.airflow_dependency_index > 0.8:
                advice.append(QApplication.translate("tilauscope_roast_assistant", "Airflow is high-impact: Avoid fan changes to keep RoR smooth."))

        return advice

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
from dataclasses import dataclass, field
from typing import Final, Any
from fpdf import FPDF, XPos, YPos
import json
import ast
import copy
import math
from pathlib import Path, PosixPath
import re
import numpy as np

from tilauscope.tilauscope_types import (AGTRON_SCALES, AgtronScale, ProbeDeviation, RoasterBasicPlan, RoasterBasicPlanPerPhase, GreenBean, RoastingPhase, marked, normalize_timeindex,
                                          get_ror_ideal_band, to_agtron, ROASTING_BASIC_BASE, clean_delta_bt, estimate_ror_dt, find_turning_point_index,
                                          which_roast_phase, find_flicks_crashes,
                                          GREEN_MOISTURE_NEUTRAL_PCT, weight_loss_target)
from tilauscope.roasters import RoasterContext
from tilauscope.alogmanager import (AlogIndex, AlogMetadata, burner_events,
                                    phase_heater)
from tilauscope import text_shaping
from tilauscope.bean_energy import FloorProfile, match_variety_family
from tilauscope.roast_plan_snapshot import (
    complete_prediction_snapshot, summarize_prediction_errors)
from artisanlib.atypes import ProfileData
from artisanlib.util import cast, fromCtoFstrict
from PyQt6.QtCore import  QSettings
from PyQt6.QtWidgets import QApplication

from artisanlib.util import convertTemp, convertWeight, fromFtoCstrict, fill_gaps, events_internal_to_external_value, smooth_list  # smooth_list moved from tgraphcanvas to util

_logd: Final[logging.Logger] = logging.getLogger('tilau')

## Le feu de séchage est TENU jusqu'à ce délai avant le DRY END. Doctrine Tilau :
## le réglage de séchage vient du setup et ne se touche pas avant ~30 s du DE.
_HOLD_LEAD_SEC: Final[float] = 30.0

## La grille porte sa propre bande `drying_time` par catégorie ; le séchage la lit
## directement (total_time = somme des trois bandes de phase).
## La Dev Ramp part du palier pre-FC et ne descend jamais de plus de
## _DEV_BURNER_DROP_CAP sous lui (le feu se TIENT en développement). Lue à la fois
## par le résumé de phase et par la Dev Ramp.
_DEV_BURNER_DROP_CAP: Final[float] = 6.0

## Charge temperature bands, in MEASURED BT (what the probe displays, no offset
## applied). Standard roasting practice: the green-coffee process sets the band;
## bean and ambient constants only modulate a few degrees inside it. The target
## roast level does NOT move the charge — it is expressed in the phase timings
## and the heater ladder instead.
## Le PROCESS encode un risque de SURFACE — les sucres d'un nature brûlent si on
## charge chaud — donc c'est un PLAFOND, pas une bande. La borne basse n'a jamais
## encodé de sécurité : charger plus froid n'est jamais dangereux, c'est seulement
## plus lent. La garder fermée écrasait toute intention de conduite plus lente sur
## un lavé, dont la borne basse valait déjà le neutre (arbitrage Tilau 2026-09-01).
_CHARGE_NEUTRAL_C: float = 185.0
## Décalage de surface par process, depuis le neutre. Reproduit les milieux des
## anciennes bandes au degré près : 185 / 175 / 165.
_CHARGE_PROCESS_OFFSET_C: dict[str, float] = {
    "washed":    0.0,
    "natural": -10.0,
    "decaf":   -20.0,
}
## Plafond de surface par process — les anciennes bornes HAUTES, inchangées.
_CHARGE_CEILING_BY_PROCESS: dict[str, float] = {
    "washed":  190.0,
    "natural": 180.0,
    "decaf":   170.0,
}
## Plancher unique, physique et non plus lié au process : sous ce niveau un lot
## ne retourne pas proprement sur un radiant. C'est l'ancienne borne basse la plus
## basse du jeu, donc rien de ce qui était atteignable ne cesse de l'être.
_CHARGE_FLOOR_C: float = 160.0
_CHARGE_MODULATION_MAX_C: float = 5.0

## ── Destination : à quoi sert ce café (Hoos 2026, étape 1) ──────────────────
## La chaîne est destination → développement → perte de masse, et elle n'a qu'un
## maillon : la destination n'entre nulle part ailleurs. Un second terme direct
## ferait doublon avec le développement et le contredirait.
## « Omni » = filtre ET espresso, donc développement médian entre les deux.
## Écart tenu petit (arbitrage Tilau) : quelques secondes de développement se
## voient en tasse, et sur les bandes claires radiantes 0:45-1:00 un écart plus
## franc sortirait de la bande.
_DEV_DESTINATION_BONUS_SEC: dict[str, float] = {
    "filter":   0.0,
    "omni":     5.0,
    "espresso": 10.0,
}
_DEV_DESTINATION_DEFAULT: str = "omni"

## ── Les variables du grain vert ──────────────────────────────────────────────
## Arbitrage Tilau 2026-08-13 (spec §2.2). aw et humidité ne sont PAS une paire :
## ce sont deux grandeurs distinctes, aux consommateurs disjoints.
##
##   HUMIDITÉ = masse d'eau = budget d'énergie. Pilote temps de séchage, feu,
##     élan au crack, Maillard, et avec la densité la charge et l'inertie finale.
##   aw = état de cette eau (fraction libre). Pilote l'air. Référence stockage.
##
## ⚠️ Aucune conversion entre les deux (banc 2026-08-13 : pente 0,019 vs 0,05
## supposée, sur deux saisies). L'absence de l'une n'est jamais comblée par l'autre.
## STRUCTURE : densité > altitude reste une paire — la mesure bat son proxy.
## L'humidité de l'AIR agit entre les roasts (dérive de l'aw), pas ici.
_AW_NEUTRAL: Final[float] = 0.60
## Graduation de l'aw sur elle-même, pas une conversion vers l'humidité.
_AW_PER_INDEX: Final[float] = 0.05
_AW_INDEX_MAX: Final[float] = 3.0            # aw 0,45–0,75
## Source unique, partagée avec la cible de perte de masse (coach) : une
## seule valeur déplace les deux.
_MOISTURE_NEUTRAL: Final[float] = GREEN_MOISTURE_NEUTRAL_PCT
_MOISTURE_POINTS_MAX: Final[float] = 3.0     # 7,5–13,5 %
_STRUCTURE_DENSITY_PER_INDEX: Final[float] = 50.0
## Bande morte de la densite, arbitrage Tilau du 2026-09-01. Le terme densite
## etait une droite centree sur 700 g/L valant jusqu'a +-7 C de charge. Compte
## sur le catalogue de reference, pondere par les torrefactions reellement
## faites : la zone que Hoos endosse (densite franchement basse, sous 650) sort
## 1 roast sur 91, et la bande 650-750 qu'il dit de NE PAS surinterpreter en
## sort 80 sur 91 — la loi consacrait donc la quasi-totalite de son autorite a
## departager des cafes qu'on ne sait pas departager, sur une valeur de fiche
## fournisseur et non une mesure par deplacement d'eau (l'ecart-type de densite
## INTRA-famille de cultivar vaut 83 % de l'ecart-type global : le champ n'a
## aucune structure grossiere). Entre les deux bornes le plan ne prononce donc
## plus rien. L'asymetrie que demande Hoos — la branche basse compte, la haute
## beaucoup moins — est portee par la LARGEUR de bande (-20 en bas, +40 en
## haut) et par la demi-pente au-dessus, pas par un plafond separe.
## ⚠️ Non calibre, et non calibrable : la charge est PRESCRITE par le plan, donc
## la relire dans le corpus renverrait la loi qu'on cherche a juger. Ce qui
## s'ameliore ici est l'accord entre ce que la loi pretend savoir et ce qu'elle
## sait, pas une justesse mesuree.
_STRUCTURE_DEAD_BAND_LOW: Final[float] = 680.0
_STRUCTURE_DEAD_BAND_HIGH: Final[float] = 740.0
_STRUCTURE_DENSE_SLOPE_WEIGHT: Final[float] = 0.5
_STRUCTURE_ALT_NEUTRAL: Final[float] = 1400.0
_STRUCTURE_ALT_PER_INDEX: Final[float] = 400.0
_STRUCTURE_INDEX_MAX: Final[float] = 2.0
## Poids du repli altitude, mesure faite le 2026-09-01 sur le catalogue de
## reference : sur les 23 fiches portant les DEUX valeurs, r(altitude, densite)
## = 0,45 — l'altitude explique donc environ 20 % de la variance de densite, et
## contredit son SIGNE 7 fois sur 23 (Raek, 626 g/L a 1800 m : la densite
## demande -5,2 C de charge, l'altitude en reclamait +3,5). Un proxy a ce
## niveau d'accord ne peut pas parler avec la voix d'une mesure : il garde sa
## graduation, il perd son autorite.
_STRUCTURE_PROXY_WEIGHT: Final[float] = 0.20

_SRC_MEASURED: Final[str] = "measured"
_SRC_PROXY: Final[str] = "proxy"
_SRC_ABSENT: Final[str] = "absent"

## Charge : ce qu'il y a à CHAUFFER — masse d'eau et structure, l'aw n'y touche pas.
## L'eau reste DANS la bande (elle module l'énergie autour du risque de surface
## que la bande encode) ; la structure s'applique APRÈS le clamp, comme le heat
## soak, parce qu'elle contredit légitimement la bande : un natural dense encaisse
## ce qu'un natural tendre ne supporte pas. Index +2 (800 g/L) = +7 °C, la
## fourchette métier (+5 à +10 sur grain très dense).
_CHARGE_C_PER_MOISTURE_POINT: Final[float] = 1.5
_CHARGE_C_PER_STRUCTURE_INDEX: Final[float] = 3.5
_CHARGE_STRUCTURE_MAX_C: Final[float] = 7.0
## Garde absolue de la charge, une fois structure et soak hors bande.
_CHARGE_ABSOLUTE_MIN_C: Final[float] = 120.0
_CHARGE_ABSOLUTE_MAX_C: Final[float] = 210.0

## Structure sur la puissance initiale : dense = puissance forte dès le TP.
## Magnitude doctrinale (±3 %) — banc bench_green_structure : non mesurable ici.
_HEATER_DRY_PCT_PER_STRUCTURE_INDEX: Final[float] = 1.5

## Température ambiante = température de DÉPART du grain (spec §7). Sur 400 g,
## 1,7 J/g·K × 10 K = 6,8 kJ ≈ 19 s de séchage aux ~350 W délivrés à la charge.
## C'est la même classe d'effet qu'un point d'eau du grain — pas un modificateur
## d'appoint. Mis à l'échelle de la masse chargée au point d'usage.
_AMBIENT_DRY_MIN_PER_10K: Final[float] = 0.19
## Ouverture d'air par index d'aw, côté eau libre seulement (chasse la vapeur).
_AIRFLOW_PCT_PER_AW_INDEX: Final[float] = 1.5
## Structure sur la durée de séchage : un grain dense retient sa vapeur plus
## longtemps. Effet volontairement petit (±0,15 min sur toute la plage).
_DRY_MIN_PER_STRUCTURE_INDEX: Final[float] = 0.075
## Écart BT entre deux crans d'air dans l'approche du DRY END.
_AIR_DE_STEP_LEAD_C: Final[float] = 6.0


@dataclass(frozen=True)
class _TechnologyProfile:
    """Everything the plan does differently because of HOW the machine heats.

    One object per heat-transfer technology, replacing the `is_fir_nir` flag
    that was tested at six separate decision sites. A new technology is a new
    instance, not a new branch.
    """
    name: str
    ## RoR au drop : bornes de la table bonnes-pratiques et bande saine.
    ror_at_drop_dark: float
    ror_at_drop_light: float
    ror_drop_floor: float
    ror_drop_ceiling: "float | None" = None
    ## Sous ce niveau la machine chauffe mais ne SOUTIENT plus la réaction : le
    ## RoR s'écroule. Plancher de prescription, pas une limite matérielle.
    burner_floor_pct: float = 0.0
    ## Pic de RoR au séchage : constante, ou suivant le brûleur prescrit.
    dry_ror_peak_c: float = 12.0
    dry_ror_peak_follows_heater: bool = False
    ## Air par phase, quand la technologie le dicte. None = interpolation sur
    ## airflow_dependency_index. Explicite = la pénalité « pull » ne s'applique
    ## pas : sur une machine où l'air SOUTIENT la réaction, ces valeurs sont
    ## déjà la cible.
    airflow_pct: "tuple[float, float, float] | None" = None
    ## Base brûleur par process en light : None = grille agtron habituelle.
    light_heater_base_by_process: "tuple[float, float, float] | None" = None
    ## Enveloppe de RoR (°C/min) : post-TP, entrée Maillard (DRY END),
    ## FC − 1:00, entrée FC. C'est la CONTRAINTE : les durées de séchage et de
    ## Maillard s'en déduisent, au lieu de sortir d'une grille de style.
    ## None = comportement historique (durées de grille, RoR géométriques).
    ror_envelope: "tuple[float, float, float, float] | None" = None
    ## Temps du TP, constante machine. None = loi de masse historique.
    tp_time_min: "float | None" = None
    ## Brûleur de séchage sous lequel le temps de TP ci-dessus n'est plus tenu.
    tp_time_heater_pct: float = 70.0
    ## Réécritures de la table de plan, par nom de catégorie.
    plan_overrides: "dict[str, dict]" = field(default_factory=dict)


## Radiant (FIR/NIR électrique — Skywalker, Kaleido, Cyberroaster).
_TECH_RADIANT: Final[_TechnologyProfile] = _TechnologyProfile(
    name="radiation",
    ror_at_drop_dark=4.0, ror_at_drop_light=5.5,
    ror_drop_floor=3.5, ror_drop_ceiling=7.0,
    burner_floor_pct=45.0,
    airflow_pct=(35.0, 45.0, 50.0),
    dry_ror_peak_c=12.0, dry_ror_peak_follows_heater=True,
    ror_envelope=(16.0, 12.0, 8.0, 5.5),
    tp_time_min=1.25, tp_time_heater_pct=70.0,
    light_heater_base_by_process=(0.0, -5.0, -10.0),
    plan_overrides={
        ## Corrections propres au rayonnement, 2026/02/18. Le développement est
        ## à 0,45 pour que l'échelle light reste monotone face au Medium Light.
        ## Bandes de développement relevées sur la machine (2026/08/13) : le
        ## radiant finit vite, 0:45-1:00 en light, 1:30 en medium light. Le
        ## dtr suit, il n'est qu'un contrôle de cohérence en aval.
        "Light": {
            "heater_cmfc": (0.65, 0.60, 0.45), "total_time": (8.0, 10.5),
            "drying_time": (3.5, 5.0), "maillard_time": (3.0, 4.0),
            "drop_temp": (201, 203),
            "development_time": (0.75, 1.0), "dtr_pct": (0.08, 0.12),
        },
        "Very Light": {
            "heater_cmfc": (0.65, 0.60, 0.45), "total_time": (8.0, 10.5),
            "drying_time": (3.5, 5.0), "maillard_time": (3.0, 4.0),
            "drop_temp": (201, 203),
            "development_time": (0.75, 1.0), "dtr_pct": (0.08, 0.12),
        },
        ## Medium light : le développement s'allonge, le total ne bouge pas —
        ## le Maillard récupère la différence (« laisser caraméliser un peu
        ## plus longtemps »).
        "Medium Light": {
            "development_time": (1.4, 1.6), "dtr_pct": (0.13, 0.16),
        },
    },
)

## Tambour classique — conduction dominante, et repli sans contexte machine.
_TECH_GENERIC: Final[_TechnologyProfile] = _TechnologyProfile(
    name="conduction",
    ror_at_drop_dark=2.0, ror_at_drop_light=3.5,
    ror_drop_floor=0.5, ror_drop_ceiling=None,
)


def _technology_profile(is_radiant_electric: bool) -> _TechnologyProfile:
    """The profile driving every heat-transfer-specific plan decision."""
    return _TECH_RADIANT if is_radiant_electric else _TECH_GENERIC


@dataclass(frozen=True)
class _GreenPairValue:
    """One resolved exclusive pair: the value, and WHICH input produced it.

    `points`/`index` is 0.0 whenever `source` is `_SRC_ABSENT`, so a caller that
    forgets to check the provenance still applies nothing — absence must never
    read as "neutral by luck".
    """
    value: float = 0.0
    source: str = _SRC_ABSENT
    label: str = ""

    @property
    def known(self) -> bool:
        return self.source != _SRC_ABSENT


def _plausible_reading(value: "float | None", lo: float, hi: float,
                       label: str) -> "float | None":
    """A reading, or None when it is absent OR outside physical reason.

    `0.0` is the codebase-wide "not measured" sentinel for bean fields — absent,
    not implausible, so it is silent. An out-of-window value is a DATA ERROR and
    is both dropped and logged: the corpus carries entry mistakes (ambientTemp
    526 °C), and clamping such a value into range would quietly turn a typo into
    an extreme-but-legal input, which is worse than ignoring it.
    """
    if value is None or float(value) == 0.0:
        return None
    if not (lo <= float(value) <= hi):
        _logd.warning(f"RoastPlan: {label} {float(value):.2f} out of plausible "
                      f"range [{lo:g}, {hi:g}] — ignored")
        return None
    return float(value)


def _resolve_green_moisture(moisture_pct: "float | None") -> _GreenPairValue:
    """The bean's WATER MASS, in points of moisture, positive = wetter.

    No fallback: aw is not a second reading of it. Not measured, no effect.
    """
    _moisture = _plausible_reading(moisture_pct, 5.0, 20.0, "bean moisture")
    if _moisture is None:
        return _GreenPairValue()
    return _GreenPairValue(
        _clamp(_moisture - _MOISTURE_NEUTRAL, -_MOISTURE_POINTS_MAX, _MOISTURE_POINTS_MAX),
        _SRC_MEASURED, f"moisture {_moisture:.1f}%")


def _resolve_green_aw(water_activity: "float | None") -> _GreenPairValue:
    """The STATE of that water — its free fraction — in index of 0.05 aw.

    Owns airflow and early convection: how readily water leaves, not how much
    there is. Never touches the energy budget, never converts to moisture points.
    """
    _aw = _plausible_reading(water_activity, 0.10, 1.0, "bean water activity")
    if _aw is None:
        return _GreenPairValue()
    return _GreenPairValue(
        _clamp((_aw - _AW_NEUTRAL) / _AW_PER_INDEX, -_AW_INDEX_MAX, _AW_INDEX_MAX),
        _SRC_MEASURED, f"aw {_aw:.2f}")


def _resolve_green_structure(density_g_l: "float | None",
                             culture_altitude_m: "float | None") -> _GreenPairValue:
    """Bean structure as a dimensionless index, positive = denser/harder.

    Density wins when measured; culture altitude is the fallback; neither means
    no effect. The altitude fallback is CENTRED and BOUNDED like the measurement
    it stands in for — the old `max(0, alt-1000)/200` was always positive and
    effectively unbounded, so at 1800 m it alone spent +4.0 °C of the ±5 cap and
    no bean could ever read as "less dense than neutral" through it.

    The fallback is also WEIGHTED DOWN, because altitude causes nothing: the
    tree answers to light, to mean temperature, to the day/night swing and to
    how fast the cherry ripens, and a coffee grown at 200 m in an ocean current
    reaches the density of one grown at 1500 m. Measured against the reference
    catalogue it agrees with density only about a fifth of the way, so it is
    given a fifth of a measurement's voice: enough to lean the plan, never
    enough to invert it. See `_STRUCTURE_PROXY_WEIGHT`.
    """
    _density = _plausible_reading(density_g_l, 250.0, 1000.0, "bean density")
    if _density is not None:
        if _density < _STRUCTURE_DEAD_BAND_LOW:
            _index = ((_density - _STRUCTURE_DEAD_BAND_LOW)
                      / _STRUCTURE_DENSITY_PER_INDEX)
        elif _density > _STRUCTURE_DEAD_BAND_HIGH:
            _index = ((_density - _STRUCTURE_DEAD_BAND_HIGH)
                      / _STRUCTURE_DENSITY_PER_INDEX
                      * _STRUCTURE_DENSE_SLOPE_WEIGHT)
        else:
            _index = 0.0
        return _GreenPairValue(
            _clamp(_index, -_STRUCTURE_INDEX_MAX, _STRUCTURE_INDEX_MAX),
            _SRC_MEASURED, f"density {_density:.0f} g/L")
    _altitude = _plausible_reading(culture_altitude_m, 1.0, 3500.0, "culture altitude")
    if _altitude is not None:
        _index = (_altitude - _STRUCTURE_ALT_NEUTRAL) / _STRUCTURE_ALT_PER_INDEX
        _index = _clamp(_index, -_STRUCTURE_INDEX_MAX, _STRUCTURE_INDEX_MAX)
        return _GreenPairValue(
            _index * _STRUCTURE_PROXY_WEIGHT,
            _SRC_PROXY, f"altitude {_altitude:.0f} m")
    return _GreenPairValue()

## RETIRÉ le 2026-08-11 — il y avait ici un seuil `_BT_TRUSTED_MIN_G = 270 g`
## sous lequel aucun roast n'était appris, au motif que la sonde BT perdait le
## contact avec la masse de grain. Le défaut n'était pas la MASSE mais la
## POSITION du grain : en surélevant légèrement les pieds arrière du Skywalker,
## l'inclinaison tasse le lot vers l'avant et la sonde reste immergée, petit lot
## compris. Un petit lot correctement chargé s'apprend donc comme un autre.
## Ne pas réintroduire de seuil de masse : si l'artefact de sonde doit être
## écarté, il faut le mesurer sur le roast lui-même, pas le présumer du poids.


@dataclass(frozen=True)
class _PlanSource:
    """Where one plan value came from: a KEY for the code, a LABEL for the eye.

    Two roles, two strings: the key is written for the code, never translated
    and never carries a count; the label is written for a human, carries the
    sample count and is free to be reworded at any time.

    Keys, by increasing support — the three tiers `_choose_coherent_history`
    grades plus the two ends:

    ==========  ===========================================================
    grid        nothing usable in the history; reference values
    reference   one real roast, shown to the operator but not adopted
    blend       two roasts, adopted half-way with the grid
    learned     three or more, the cohort's representative adopted as it is
    skeleton    real roasts, but only their thermal geometry (no logged hand)
    coherence   not history: rebuilt from the first-crack anchor
    ==========  ===========================================================
    """
    key:   str
    n:     int = 0
    label: str = ""

    def __str__(self) -> str:
        # Anything that still interpolates a source renders the label, so a
        # missed call site degrades to the old display text, never to a raw
        # repr in front of the operator.
        return self.label or self.key

    @property
    def is_grid(self) -> bool:
        return self.key == _SRC_GRID


_SRC_GRID:      Final[str] = "grid"
_SRC_REFERENCE: Final[str] = "reference"
_SRC_BLEND:     Final[str] = "blend"
_SRC_LEARNED:   Final[str] = "learned"
_SRC_SKELETON:  Final[str] = "skeleton"
#: Not history at all: the drop was rebuilt from the FC anchor because the
#: learned one was geometrically unreachable. Scores as grid on purpose.
_SRC_COHERENCE: Final[str] = "coherence"

#: The one instance every "nothing learned" path returns.
_SOURCE_GRID: Final[_PlanSource] = _PlanSource(_SRC_GRID, 0, "grid")


def _clamp(value: float, between_min: float, between_max: float) -> float:
    return max(between_min, min(between_max, value))

def _mean(low:float, high:float) -> float:
    return (low + high) * 0.5

# P0 learning rules kept pure so legacy logs and sensor glitches are
# handled identically by the scanner and by focused regression tests.
def _learning_log_is_eligible(data: dict) -> bool:
    if data.get("tilau_simulated") is True:
        return False
    if data.get("tilau_exclude_learning") is True:
        return False
    computed = data.get("computed") or {}
    try:
        temp = float(computed.get("ambient_temperature", 0.0) or 0.0)
        humidity = float(computed.get("ambient_humidity", 0.0) or 0.0)
    except (TypeError, ValueError):
        return False
    return -10.0 <= temp <= 60.0 and 0.0 < humidity <= 100.0 and temp != 0.0


def _selected_roast_color(data: dict) -> "tuple[float | None, str | None]":
    """Return the selected raw colour and its measurement basis.

    A positive ground reading has priority; whole-bean colour is only a
    fallback. Conversion to Agtron is deliberately left to the single caller.
    """
    for key, basis in (("ground_color", "ground"), ("whole_color", "whole")):
        try:
            value = float(data.get(key, 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if value > 0.0:
            return value, basis
    return None, None


def _fit_fc_charge_regression(charges: "list[float]", fcs: "list[float]",
                              planned_charge_c: "float | None" = None) -> dict:
    """Validate an FC/charge regression against leave-one-out median baseline.

    ⚠️ Every roast takes part, small batches included — the rear-elevation
    loading technique keeps the probe immersed, so batch mass is not a reason
    to distrust a reading (doctrine corrected 2026-08-11).

    Leave-one-out remains the ONLY gate, and it has a known blind spot worth
    remembering: a systematic probe artefact is systematically predictable, so
    validation rewards it instead of refusing it. Should such an artefact ever
    need excluding again, detect it on the roast itself — never presume it from
    the batch weight.
    """
    result = {"n": min(len(charges), len(fcs)), "charge_range_c": 0.0,
              "charge_min_c": None, "charge_max_c": None,
              "regression_mae_c": None, "baseline_mae_c": None,
              "status": "refused", "reason": "insufficient samples",
              "slope": None, "offset": None}
    if len(charges) != len(fcs) or len(charges) < 5:
        return result
    x = np.asarray(charges, dtype=float)
    y = np.asarray(fcs, dtype=float)
    span = float(np.ptp(x))
    result["charge_range_c"] = round(span, 2)
    result["charge_min_c"] = round(float(np.min(x)), 2)
    result["charge_max_c"] = round(float(np.max(x)), 2)
    if span < 10.0:
        result["reason"] = "charge range below 10°C"
        return result
    if planned_charge_c is not None and not (float(np.min(x)) - 2.0 <= planned_charge_c
                                              <= float(np.max(x)) + 2.0):
        result["reason"] = "planned charge outside observed range"
        return result
    regression_errors: list[float] = []
    baseline_errors: list[float] = []
    for i in range(len(x)):
        train_x = np.delete(x, i)
        train_y = np.delete(y, i)
        if float(np.ptp(train_x)) <= 0.0:
            result["reason"] = "zero training variance"
            return result
        slope, offset = np.polyfit(train_x, train_y, 1)
        regression_errors.append(abs(float(slope * x[i] + offset - y[i])))
        baseline_errors.append(abs(float(np.median(train_y) - y[i])))
    reg_mae = float(np.mean(regression_errors))
    base_mae = float(np.mean(baseline_errors))
    result["regression_mae_c"] = round(reg_mae, 3)
    result["baseline_mae_c"] = round(base_mae, 3)
    if base_mae <= 0.0 or reg_mae > base_mae * 0.9:
        result["reason"] = "leave-one-out improvement below 10%"
        return result
    slope, offset = np.polyfit(x, y, 1)
    result.update(status="adopted", reason="validated", slope=round(float(slope), 4),
                  offset=round(float(offset), 2))
    return result


def _heater_authority_notes(pre_fc_values: "list[float]",
                            support_threshold: "float | None",
                            caution_threshold: "float | None",
                            roaster_name: str = "") -> "list[str]":
    """Describe low heater authority before FC without changing a setpoint.

    The thresholds are a MACHINE observation and only exist on machines that
    have been measured — today the Cyberroaster alone (45 / 50 %). The note is
    therefore worded neutrally and filled from the roaster it is talking about:
    naming one machine inside the sentence made every other roaster that ever
    declares these fields quote the Skywalker at its owner, and it silently
    contradicted the values actually being applied.
    """
    if support_threshold is None or caution_threshold is None or not pre_fc_values:
        return []
    machine = roaster_name or QApplication.translate(
        "tilauscope_roast_plan", "this roaster")
    low = min(pre_fc_values)
    if low < support_threshold:
        return [QApplication.translate(
            "tilauscope_roast_plan",
            "Below about {0}% on the {1}, the remaining heater power generally no longer sustains the rate of rise. This is a low-authority zone, not an electrical cut-off.").format(
            f"{support_threshold:.0f}", machine)]
    if low < caution_threshold:
        return [QApplication.translate(
            "tilauscope_roast_plan",
            "The planned pre-first-crack heater enters the {0}–{1}% low-margin zone on the {2}; use the live rate of rise to decide whether to hold or adjust it.").format(
            f"{support_threshold:.0f}", f"{caution_threshold:.0f}", machine)]
    return []


def _cohort_profile_vector(profile: dict) -> dict[str, float]:
    """Flatten the robust dimensions used to compare complete roast profiles."""
    keys = (
        "dry_time_min", "maillard_time_min", "dev_time_min",
        "heater_dry", "heater_maillard", "heater_dev", "heater_fc",
        "airflow_dry", "airflow_maillard", "airflow_dev",
        "fc_bt_c", "drop_bt_c", "drop_ror_c",
    )
    out: dict[str, float] = {}
    for key in keys:
        value = profile.get(key)
        if value is not None and math.isfinite(float(value)):
            out[key] = float(value)
    for etype, per_fraction in (profile.get("dev_trajectory") or {}).items():
        if int(etype) not in (0, 3):  # air and heater define the control shape
            continue
        for fraction, value in per_fraction.items():
            out[f"trajectory_{int(etype)}_{float(fraction):.2f}"] = float(value)
    return out


def _select_cohort_medoid(profiles: "list[dict]") -> "dict | None":
    """Return the real roast minimizing total robust distance to its cohort.

    Every dimension is normalized by its cohort MAD. If MAD collapses to zero
    because most roasts share a value, the largest absolute deviation supplies
    a unit-free fallback scale; fully constant dimensions still add zero.
    Missing optional dimensions are ignored pairwise; the mean shared distance
    prevents sparse rows from being favoured merely because they expose fewer
    values.
    """
    if not profiles:
        return None
    vectors = [_cohort_profile_vector(profile) for profile in profiles]
    dimensions = sorted({key for vector in vectors for key in vector})
    scales: dict[str, float] = {}
    for key in dimensions:
        values = [vector[key] for vector in vectors if key in vector]
        median = float(np.median(values))
        deviations = [abs(value - median) for value in values]
        mad = float(np.median(deviations))
        scales[key] = mad if mad > 1e-9 else max(max(deviations, default=0.0), 1.0)

    totals: list[float] = []
    for i, vector_i in enumerate(vectors):
        pair_distances: list[float] = []
        for j, vector_j in enumerate(vectors):
            if i == j:
                continue
            shared = vector_i.keys() & vector_j.keys()
            if not shared:
                continue
            pair_distances.append(float(np.mean([
                abs(vector_i[key] - vector_j[key]) / scales[key] for key in shared
            ])))
        totals.append(sum(pair_distances) if pair_distances else 0.0)
    winner = min(range(len(profiles)), key=lambda i: (totals[i], str(profiles[i].get("id", ""))))
    selected = copy.deepcopy(profiles[winner])
    selected["medoid_distance"] = round(totals[winner], 4)
    return selected


def _select_two_roast_reference(profiles: "list[dict]", planned_mass_g: float,
                                target_agtron: float) -> "dict | None":
    """Choose one real roast for the cautious two-observation grid blend."""
    if not profiles:
        return None
    def score(profile: dict) -> tuple[float, str]:
        mass_scale = max(planned_mass_g, 1.0)
        mass_gap = abs(float(profile.get("batch_g") or planned_mass_g) - planned_mass_g) / mass_scale
        colour_gap = abs(float(profile.get("agtron") or target_agtron) - target_agtron) / 10.0
        return mass_gap + colour_gap, str(profile.get("id", ""))
    return copy.deepcopy(min(profiles, key=score))


def _choose_coherent_history(profiles: "list[dict]", planned_mass_g: float,
                             target_agtron: float
                             ) -> "tuple[dict | None, int, _PlanSource, str | None]":
    """Apply the P1 cohort-basis and 0/1/2/3+ fallback policy.

    The third element grades the support: see _PlanSource for why it carries a
    stable key alongside the label the plan prints.
    """
    ground = [profile for profile in profiles if profile.get("color_basis") == "ground"]
    whole = [profile for profile in profiles if profile.get("color_basis") == "whole"]
    if len(ground) >= 2:
        cohort, basis = ground, "ground"
    elif whole:
        cohort, basis = whole, "whole"
    else:
        cohort, basis = ground, ("ground" if ground else None)
    count = len(cohort)
    if count >= 3:
        return (_select_cohort_medoid(cohort), count,
                _PlanSource(_SRC_LEARNED, count, f"medoid (n={count})"), basis)
    if count == 2:
        return (_select_two_roast_reference(cohort, planned_mass_g, target_agtron),
                count, _PlanSource(_SRC_BLEND, count, "grid/profile blend (n=2)"), basis)
    if count == 1:
        return (copy.deepcopy(cohort[0]), count,
                _PlanSource(_SRC_REFERENCE, count, "reference only (n=1)"), basis)
    return None, 0, _SOURCE_GRID, None

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
class _GreenMoistureEffect:
    """Deltas from the bean's WATER MASS — the energy budget — all zero when
    the moisture was not measured.

    The charge is not here: it is driven from inside the charge modulation, so
    the term cannot collide with the heat soak past the band clamp. Airflow is
    not here either: it belongs to the aw (evaporation, not energy).
    """
    d_dry_time_min:      float = 0.0
    d_heater_dry_pct:    float = 0.0
    ## Élan à travers le crack : le grain tient encore ~4-5 % d'eau au FC, et
    ## c'est cette vapeur sous pression qui le fait éclater. Un lot humide perd
    ## son élan là (Arnephy) — la vapeur a une chaleur massique assez élevée
    ## pour absorber l'énergie qu'on y pousse.
    d_heater_fc_pct:     float = 0.0
    ## Corps : moins d'eau = moins de pression interne = le mur de pression ne
    ## se bâtit pas = tasse plate, indépendamment du développement (Hoos). Son
    ## levier de corps est la durée de Maillard, pas la chaleur.
    d_maillard_time_min: float = 0.0

@dataclass(frozen=True)
class _PhaseDurationCalibration:
    """Result of the cross-roast timing calibration and the physical duration
    floors that follow it (banc 2026-08-05): the final drying/Maillard
    durations, where they came from, the two calibration heater nudges, and
    the operator notes for the caller to append to history["actions"]."""
    dry_time_min:       float
    maillard_time_min:  float
    timing_source:      "_PlanSource"
    cal_heater_dry_pct: float
    cal_heater_mai_pct: float
    notes: "list[str]"


@dataclass(frozen=True)
class _EnvelopeTiming:
    """Durations and slopes deduced from the technology's RoR envelope (lot 4).

    The envelope constrains, the durations follow — see _envelope_timing.
    `dev_delta_c` is the rise development is allowed to make, from which the
    drop temperature is worked out instead of being read off a colour band."""
    dry_time_min:      float
    maillard_time_min: float
    dry_ror_c:         float
    maillard_ror_c:    float
    fc_entry_ror_c:    float
    dev_delta_c:       float
    ## Le séchage a été rallongé pour ne pas passer sous le Maillard (recours).
    drying_stretched:  bool = False
    ## Le Maillard a été resserré sur la durée du séchage (cas normal).
    maillard_compressed: bool = False
    ## Décalage à appliquer au DRY END pour que la courbe reste descendante.
    dry_bt_shift_c:    float = 0.0

@dataclass(frozen=True)
class _ChargeSetup:
    """Charge band by process, bean/ambient modulation (capped), and
    inter-batch heat-soak correction (banc 2026-08-05).

    `nominal_temperature_c` is the pre-modulation band midpoint, BEFORE the
    cultivar-family prior: it is still needed by the caller after this stage
    returns, for the FC regression, which the original code interleaves
    between the band and the modulation — and that regression is learned from
    charges actually practised, so a declared prior has no business shifting
    it. `temperature_c` is the final charge BT, family prior, modulation and
    heat soak included. `band` is the process band the modulation is clamped
    into."""
    band: "tuple[float, float]"
    nominal_temperature_c: float
    temperature_c: float
    soak_dcharge_c: float = 0.0
    soak_dheater_pct: int = 0
    soak_tau_min: float = 0.0
    ## Ce que la famille de cultivar a réellement déplacé, pour que l'opérateur
    ## voie le prior au lieu de le subir. Vide/0 = aucune famille reconnue.
    family_name: str = ""
    family_delta_c: float = 0.0

@dataclass(frozen=True)
class _DropAndDevRor:
    """Learned-drop adoption from measured colours, the FC→DROP coherence
    rebuild, and the development/drop RoR derivation (banc 2026-08-05): the
    final drop BT and its source, the development RoR, the RoR at drop and
    its source, and the operator notes for the caller to append to
    history["actions"]."""
    drop_bt_temperature: float
    drop_source: "_PlanSource"
    dev_ror: float
    drop_ror: float
    drop_ror_source: "_PlanSource"
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
    heater_source: "_PlanSource"
    heater_fc_source: "_PlanSource"
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
    dev_ramp_source: "_PlanSource"

@dataclass(frozen=True)
class _PlanConfidence:
    """History support, tolerance factor, and the heat-soak operator note.

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
        ## Destination du café. Lue en réglage plutôt que passée en paramètre :
        ## les trois appelants de generate_roast_plan (dont le replan en cours de
        ## roast) restent inchangés. Relue à CHAQUE plan — le moteur est mis en
        ## cache par ses appelants, donc une valeur figée ici resterait celle du
        ## premier plan alors que l'utilisateur peut changer de destination.
        self.roast_destination: str = self._read_roast_destination()
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

        # Corpus index snapshot, resolved lazily and held for this instance's
        # lifetime. It is the pre-filter for every historical scan below.
        self._index_snapshot: "dict[str, AlogMetadata] | None" = None

    def _list_alogs(self):
        if not self.alog_directory or not Path(self.alog_directory).is_dir():
            return []
        return [f for f in Path(self.alog_directory).iterdir() if f.is_file() and f.suffix == '.alog']

    # ── Corpus index ─────────────────────────────────────────────────────────
    # Every quality filter below reads scalars the index already holds (green
    # weight, charge BT, TP temps, ambient, learning flags, bean field). Testing
    # them BEFORE opening the profile is what keeps plan generation off the
    # 240 KB-per-log parse path: only the handful of logs that survive is read.

    def _index_records(self) -> "dict[str, AlogMetadata]":
        """Index snapshot for the current alog directory. Never blocks on disk."""
        if self._index_snapshot is None:
            try:
                self._index_snapshot = AlogIndex.instance().records(Path(self.alog_directory))
            except Exception as exc:  # noqa: BLE001 — no index is not an error
                _logd.debug(f"RoastPlan: corpus index unavailable ({exc})")
                self._index_snapshot = {}
        return self._index_snapshot

    def _index_meta(self, log) -> "AlogMetadata | None":
        return self._index_records().get(str(log))

    @staticmethod
    def _meta_charge_bt_c(meta: "AlogMetadata") -> float:
        """Charge BT normalised to °C — computed values carry the LOG's unit."""
        raw = float(meta.computed.get("CHARGE_BT", 0.0) or 0.0)
        return fromFtoCstrict(raw) if (meta.mode == "F" and raw > 0.0) else raw

    @staticmethod
    def _meta_learning_eligible(meta: "AlogMetadata") -> bool:
        """Index-side mirror of _learning_log_is_eligible()."""
        if meta.simulated or meta.exclude_learning:
            return False
        try:
            temp = float(meta.computed.get("ambient_temperature", 0.0) or 0.0)
            humidity = float(meta.computed.get("ambient_humidity", 0.0) or 0.0)
        except (TypeError, ValueError):
            return False
        return -10.0 <= temp <= 60.0 and 0.0 < humidity <= 100.0 and temp != 0.0

    def _prefilter_logs(self, logs, *, charge_weight_g: float = 0.0,
                        weight_tol_ratio: "float | None" = None,
                        weight_tol_abs: "float | None" = None,
                        require_eligible: bool = True,
                        process_needle: str = "") -> list:
        """Drop the logs the in-loop filters would reject anyway.

        Conservative by construction: a log with no index entry is KEPT, so the
        full path stays authoritative and a stale or missing index can only cost
        time, never change which roasts the plan learns from.
        """
        records = self._index_records()
        if not records:
            return list(logs)
        _is_radiant = (self._roaster_ctx.is_radiant_electric
                       if self._roaster_ctx is not None else None)
        kept = []
        for log in logs:
            meta = records.get(str(log))
            if meta is None:
                kept.append(log)
                continue
            if require_eligible and not self._meta_learning_eligible(meta):
                continue
            charge_bt_c = self._meta_charge_bt_c(meta)
            if 0.0 < charge_bt_c < 150.0:
                continue
            if process_needle and process_needle not in meta.bean_field.lower():
                continue
            if charge_weight_g > 0.0 and (weight_tol_ratio is not None
                                          or weight_tol_abs is not None):
                if meta.weight_in_g <= 0.0:
                    continue
                delta = abs(meta.weight_in_g - charge_weight_g)
                if weight_tol_abs is not None and delta > weight_tol_abs:
                    continue
                if (weight_tol_ratio is not None
                        and delta / charge_weight_g > weight_tol_ratio):
                    continue
            if _is_radiant is not None:
                tp_bt = float(meta.computed.get("TP_BT", 0.0) or 0.0)
                tp_et = float(meta.computed.get("TP_ET", 0.0) or 0.0)
                if tp_bt > 0.0 and tp_et > 0.0:
                    tp_delta = (tp_et - tp_bt) / (1.8 if meta.mode == "F" else 1.0)
                    if _is_radiant and tp_delta < -5.0:
                        continue
                    if not _is_radiant and tp_delta > 5.0:
                        continue
            kept.append(log)
        return kept

    def _load_phase_times(self, file_name):
        """Load a profile and derive its phase_times — no RoR, no smoothing.

        _get_delta_bt() computes the whole smoothed RoR series; callers that
        only need the phase boundaries (the cohort burner scan) paid that for
        nothing. Sets self.lastprofiledata exactly like _get_delta_bt does, so
        _extract_phase_heater() reads the same profile afterwards.
        """
        try:
            with open(file=Path(self.alog_directory) / file_name, encoding="utf-8") as f:
                self.lastprofiledata = cast('ProfileData', ast.literal_eval(f.read()))
        except (OSError, ValueError, SyntaxError) as exc:
            _logd.debug(f"_load_phase_times: unreadable {file_name} ({exc})")
            return None
        ti = normalize_timeindex(self.lastprofiledata.get("timeindex", []))
        tx = self.lastprofiledata.get("timex", [])
        if (not tx or not marked(ti, RoastingPhase.CHARGE)
                or not marked(ti, RoastingPhase.DROP)):
            return None
        if ti[RoastingPhase.DROP] <= ti[RoastingPhase.CHARGE]:
            return None  # zero-length roast — _get_delta_bt returns empty slices here too
        charge_ts = tx[ti[RoastingPhase.CHARGE]]
        return {
            "dry_end":  tx[ti[RoastingPhase.DRYEND]]  - charge_ts if ti[RoastingPhase.DRYEND]  > 0 else None,
            "fc_start": tx[ti[RoastingPhase.FCSTART]] - charge_ts if ti[RoastingPhase.FCSTART] > 0 else None,
            "drop":     tx[ti[RoastingPhase.DROP]]    - charge_ts,
        }

    # Thin delegators onto the shared tilauscope_types implementations (single
    # source with the BeanCave coach) — kept as methods for the existing test
    # suite and internal call sites.
    def _clean_delta_bt(self, delta_bt: list) -> list:
        return clean_delta_bt(delta_bt)

    def _estimate_dt(self, timex) -> float:
        return estimate_ror_dt(timex)

    def _find_turning_point_index(self, bt_input: list, dt: float = 1.0) -> int:
        return find_turning_point_index(bt_input, dt)

    def _which_phase(self, current_time: float, phase_times: dict) -> int:
        return which_roast_phase(current_time, phase_times)

    def _find_flicks_crashes(self, delta_bt: list, timex: list, phase_times: dict, tp_index: int,
                              prominence: float = 1.0, debounce_sec: float = 20.0, recovery_margin_sec: float = 30.0):
        return find_flicks_crashes(delta_bt, timex, phase_times, tp_index, prominence, debounce_sec, recovery_margin_sec)

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
        ti = normalize_timeindex(self.lastprofiledata.get("timeindex", []))
        if not marked(ti, RoastingPhase.CHARGE) or not marked(ti, RoastingPhase.DROP):
            return None, None, None, None, None
        if ti[RoastingPhase.DROP] <= ti[RoastingPhase.CHARGE]:
            return None, None, None, None, None  # zero-length roast: empty slices downstream

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

        delta_bt_input = clean_delta_bt(self.evaldeltas(self.lastprofiledata, "temp2"))
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
        dt = estimate_ror_dt(timex_shifted[start:end])
        # TP = BT minimum (NOT the RoR minimum). Reverts the earlier mis-"fix" that
        # passed delta_bt; the RoR minimum is the steepest-cooling point, before TP.
        tp_index = find_turning_point_index(bt_input[start:end], dt)

        return (
            delta_bt_input[start:end],
            timex_shifted[start:end],
            bt_input[start:end],
            tp_index,
            phase_times,         # remplace ti_shifted
        )

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
        records = self._index_records()
        matches = []
        for log in historical_logs:
            meta = records.get(str(log))
            if meta is not None:
                # The index already carries the uuid parsed out of the bean
                # field; the substring scan below is the fallback for a log the
                # index has not caught up with yet.
                if meta.uuid.lower() == needle or needle in meta.bean_field.lower():
                    matches.append(log)
                continue
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

        Délégation vers alogmanager.burner_events : l'index du corpus lit la
        main de l'opérateur avec exactement ce code. Deux lectures séparées,
        c'est se garantir qu'elles divergeront.
        """
        return burner_events(data, charge_ts)

    ## Bruit de charge : les premières secondes portent la montée du réglage
    ## initial (65→90→75 en 2 s), qui n'est pas une conduite de roast.
    _DESCENT_IGNORE_SEC: Final[float] = 15.0
    ## Une baisse plus petite n'est pas un geste : c'est la résolution du curseur.
    _DESCENT_MIN_PCT: Final[float] = 1.0
    ## Largeur de la cohorte autour de la masse cible (lot 5).
    _COHORT_WEIGHT_TOL_G: Final[float] = 50.0

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
        ## Corps délégué à alogmanager.phase_heater : l'index stocke ces cinq
        ## valeurs par torréfaction, calculées par cette même fonction.
        return phase_heater(self.lastprofiledata, phase_times)

    def _extract_phase_control(self, phase_times: dict, event_type: int
                               ) -> "tuple[float | None, float | None, float | None]":
        """Return one control's held value at each phase midpoint."""
        try:
            data = self.lastprofiledata
            evt_idx = data.get("specialevents", []) or []
            evt_type = data.get("specialeventstype", []) or []
            evt_val = data.get("specialeventsvalue", []) or []
            time_index = data.get("timeindex", []) or []
            timex = data.get("timex", []) or []
            if not (evt_idx and time_index and timex) or time_index[RoastingPhase.CHARGE] < 0:
                return None, None, None
            charge_ts = float(timex[time_index[RoastingPhase.CHARGE]])
            events: list[tuple[float, float]] = []
            for index, kind, value in zip(evt_idx, evt_type, evt_val):
                if int(kind) != event_type or not (0 <= int(index) < len(timex)):
                    continue
                pct = float(events_internal_to_external_value(float(value)))
                if 0.0 <= pct <= 100.0:
                    events.append((float(timex[int(index)]) - charge_ts, pct))
            events.sort()
            def held_at(moment: float) -> "float | None":
                held = None
                for timestamp, value in events:
                    if timestamp <= moment + 1e-6:
                        held = value
                    else:
                        break
                return held
            dry = phase_times.get("dry_end")
            fc = phase_times.get("fc_start")
            drop = phase_times.get("drop")
            return (
                held_at(dry / 2.0) if dry and dry > 0 else None,
                held_at((dry + fc) / 2.0) if dry and fc and fc > dry else None,
                held_at((fc + drop) / 2.0) if fc and drop and drop > fc else None,
            )
        except (KeyError, IndexError, TypeError, ValueError) as error:
            _logd.debug("_extract_phase_control failed: %s", error)
            return None, None, None

    # etypes des leviers dont on apprend la trajectoire de développement
    _DEV_TRAJ_ETYPES: "tuple[int, ...]" = (0, 2, 3)   # air, extraction, burner
    _DEV_TRAJ_FRACS:  "tuple[float, ...]" = (0.25, 0.5, 0.75, 1.0)

    def _extract_dev_trajectory(self, phase_times: dict
                                ) -> "dict[int, dict[float, float]] | None":
        """Trajectoire CONTINUE tenue en développement (FC→DROP) sur
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

    def _cohort_charge_burner(self, *, process_type: str, charge_weight_g: float
                              ) -> "tuple[float | None, int]":
        """Brûleur de charge de la COHORTE : même process, masse cible ± 50 g,
        toutes origines confondues (lot 5).

        La famille — les torréfactions du même grain — dit les durées, la
        couleur et les accidents de courbe. Elle ne dit PAS comment la machine
        chauffe : le grain n'a pas d'avis là-dessus, la masse et le process si.
        Le brûleur de charge quitte donc la famille pour la cohorte. Le
        Maillard et le développement restent au grain, eux : leur valeur suit
        la couleur visée.

        Renvoie (médiane du brûleur de séchage, nombre de torréfactions).
        """
        if charge_weight_g <= 0.0 or not process_type:
            return None, 0
        _key = ("cohort", process_type.strip().lower(), round(charge_weight_g))
        if _key in self._history_cache:
            _hit = self._history_cache[_key]
            return (_hit or {}).get("value"), int((_hit or {}).get("n", 0))

        _is_radiant = (self._roaster_ctx.is_radiant_electric
                       if self._roaster_ctx is not None else None)
        _needle = process_type.strip().lower()
        _samples: "list[float]" = []
        ## Le process est écrit en clair dans le champ `beans` du .alog
        ## (« Process: Washed / Wet Process ») — pas besoin de la fiche.
        ## Tous les critères de cohorte (process, masse, brûleur de charge,
        ## empreinte machine, éligibilité) se lisent dans l'index : seuls les
        ## survivants sont ouverts, et sans calculer leur courbe de RoR — le
        ## brûleur de phase ne dépend que des jalons.
        _candidates = self._prefilter_logs(
            self._list_alogs(), charge_weight_g=charge_weight_g,
            weight_tol_abs=self._COHORT_WEIGHT_TOL_G, process_needle=_needle)
        _records = self._index_records()
        for log in _candidates:
            ## Le brûleur de séchage est déjà dans l'index, lu par la même
            ## fonction que le plan (alogmanager.phase_heater). Sur un log
            ## indexé et complet, la cohorte n'ouvre donc aucun fichier ; on ne
            ## retombe sur le profil que si l'index ne peut pas répondre.
            _meta = _records.get(str(log))
            if _meta is not None and _meta.heater_read:
                if _meta.heater_dry is not None:
                    _samples.append(_meta.heater_dry)
                continue
            phase_times = self._load_phase_times(log)
            if phase_times is None or not _learning_log_is_eligible(self.lastprofiledata):
                continue
            _computed = self.lastprofiledata.get("computed", {})
            _log_is_f = str(self.lastprofiledata.get("mode", "C")) == "F"
            _charge_bt = _computed.get("CHARGE_BT", 0.0) or 0.0
            _charge_bt_c = fromFtoCstrict(_charge_bt) if (_log_is_f and _charge_bt > 0.0) else _charge_bt
            if 0.0 < _charge_bt_c < 150.0:
                continue
            if _needle not in str(self.lastprofiledata.get("beans", "")).lower():
                continue
            _w = self.lastprofiledata.get("weight")
            _w_green = 0.0
            if _w:
                try:
                    _w_green = convertWeight(float(_w[0]), ["g", "Kg", "lb", "oz"].index(str(_w[2])), 0)
                except (ValueError, TypeError, IndexError):
                    _w_green = 0.0
            if _w_green <= 0.0 or abs(_w_green - charge_weight_g) > self._COHORT_WEIGHT_TOL_G:
                continue
            if _is_radiant is not None:
                _tp_bt = _computed.get("TP_BT", 0.0) or 0.0
                _tp_et = _computed.get("TP_ET", 0.0) or 0.0
                if _tp_bt > 0.0 and _tp_et > 0.0:
                    _tp_delta = (_tp_et - _tp_bt) / (1.8 if _log_is_f else 1.0)
                    if _is_radiant and _tp_delta < -5.0:
                        continue
                    if not _is_radiant and _tp_delta > 5.0:
                        continue
            _h_dry, _, _, _, _ = self._extract_phase_heater(phase_times)
            if _h_dry is not None:
                _samples.append(_h_dry)

        _value = round(float(np.median(_samples)), 1) if _samples else None
        self._history_cache[_key] = {"value": _value, "n": len(_samples)}
        _logd.info(f"RoastPlan: cohort '{_needle}' at {charge_weight_g:.0f}g — "
                   f"n={len(_samples)}, charge burner {_value}")
        return _value, len(_samples)

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
        # 1. Bean identity — uuid is authoritative when the bean has one: zero
        # uuid hits means "no history for THIS bean" (fresh bean → grid plan).
        # Fuzzy filename match applies only to beans without a BeanCave uuid.
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
        # Never pool whole and ground readings in learned statistics.
        drop_color_samples_c: dict[str, list[float]] = {"ground": [], "whole": []}
        peak_ror_samples: list[float] = []       # RoR peak (~2:41, °C/min) — bean property, drives the setup loop
        # Heater réellement tenu par phase — COULEUR-ASSORTIE (collecté sous le
        # gate Agtron) : le heater de dev dépend fortement de la cible couleur.
        heater_dry_samples:  list[float] = []
        heater_mai_samples:  list[float] = []
        heater_dev_samples:  list[float] = []
        heater_fc_samples:   list[float] = []   # item C : feu tenu AU FC
        # Feu tenu AU DRY END : point d'arrivée du séchage.
        heater_de_samples:   list[float] = []
        # Premier geste de descente EFFECTIVE avant le DRY END : son avance sur
        # le jalon, et la taille des crans de l'opérateur sur cette descente.
        pre_de_lead_samples: list[float] = []
        pre_de_step_samples: list[float] = []
        # RoR au drop réellement obtenu — COULEUR-ASSORTI (le RoR de fin de
        # courbe dépend de la cible couleur/DTR). Spec Bench-Integration item A.
        drop_ror_samples_c:  list[float] = []
        # Trajectoire DEV apprise (air/ext/burner × fractions de phase) —
        # samples[etype][frac] = liste de % tenus ; médiane par (levier, frac).
        dev_traj_samples: "dict[int, dict[float, list[float]]]" = {
            et: {f: [] for f in self._DEV_TRAJ_FRACS} for et in self._DEV_TRAJ_ETYPES}
        # P1: complete, colour-matched real-roast candidates.
        coherent_profiles: list[dict] = []
        ## Same roasts minus a usable control hand — see the skeleton/controls
        ## split at the collection site. Kept apart so they can only ever be a
        ## LAST RESORT: they are consulted when fewer than two complete profiles
        ## exist, i.e. exactly where the plan would otherwise be pure grid.
        skeleton_profiles: list[dict] = []
        # P2: predictions are selected by their pre-roast target,
        # never by the actual colour (which would bias errors toward successes).
        prediction_snapshots: list[dict] = []
        # Index pre-pass: quality filters 1-4 below all read scalars the index
        # holds, so the logs they would reject are dropped before being parsed.
        # The in-loop checks stay as the authority — a log the index does not
        # know is kept and judged on the profile itself.
        potential_logs = self._prefilter_logs(
            potential_logs, charge_weight_g=charge_weight_g, weight_tol_ratio=0.25)
        for log in potential_logs:
            delta_bt, timex, bt, tp_index, phase_times = self._get_delta_bt(log)

            if not delta_bt:
                continue

            # ── Learning exclusions ─────────────────────────────────────────
            # Simulated roasts (tilau_simulated, stamped at save) are not
            # physical data; tilau_exclude_learning is the operator's explicit
            # veto from the EOR page. Both were already honoured by the
            # adaptive PID — the plan learning must skip them too.
            if not _learning_log_is_eligible(self.lastprofiledata):
                _logd.debug(f"_analyze_historical_roasts: skipping {log.name} — learning flag or ambient data")
                continue

            # ── Data quality filter 1: ambient conditions ──────────────────
            _ambient_temp = self.lastprofiledata.get("computed", {}).get("ambient_temperature", 0.0) or 0.0
            _ambient_hum  = self.lastprofiledata.get("computed", {}).get("ambient_humidity",    0.0) or 0.0
            # Validity bounds were checked by _learning_log_is_eligible above.

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
            _w_green = 0.0
            if charge_weight_g > 0.0:
                _w = self.lastprofiledata.get("weight")
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

            _snapshot = self.lastprofiledata.get("tilau_roast_plan_snapshot")
            if isinstance(_snapshot, dict):
                try:
                    _snapshot_target = float(
                        (_snapshot.get("predicted") or {}).get("target_color_agtron"))
                    if (target_agtron.agtron_range.min_value <= _snapshot_target
                            <= target_agtron.agtron_range.max_value):
                        prediction_snapshots.append(complete_prediction_snapshot(
                            _snapshot, self.lastprofiledata))
                except (TypeError, ValueError):
                    pass

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

            # ── DROP learning: raw DROP BT, same target colour category only.
            # Ground and whole-bean measurements stay in separate cohorts.
            _drop_log  = self.lastprofiledata.get("computed", {}).get("DROP_BT", 0.0) or 0.0
            _raw_color, _color_basis = _selected_roast_color(self.lastprofiledata)
            _color_log = (to_agtron(_raw_color, self.lastprofiledata.get("color_system", ""))
                          if _raw_color is not None else 0.0)
            if (_drop_log > 0.0 and _color_basis is not None
                    and target_agtron.agtron_range.min_value <= _color_log
                    <= target_agtron.agtron_range.max_value):
                _drop_c = (fromFtoCstrict(float(_drop_log)) if _log_is_f else float(_drop_log))
                drop_color_samples_c[_color_basis].append(_drop_c)

            # ── Timing calibration samples — same pre-Agtron rationale: the
            # time to dry-end / to FC barely depends on the target colour.
            # Paired samples only (both events marked, in the right order).
            _dry_t = self.lastprofiledata.get("computed", {}).get("DRY_time", 0.0) or 0.0
            _fcs_t = self.lastprofiledata.get("computed", {}).get("FCs_time", 0.0) or 0.0
            if _dry_t > 0.0 and _fcs_t > _dry_t:
                dry_time_samples_min.append(float(_dry_t) / 60.0)
                fc_time_samples_min.append(float(_fcs_t) / 60.0)

            # ── Peak RoR learning sample — PRE-Agtron-gate (bean property, the
            # anchor of the descent, ~2:41). Drives the cross-roast setup loop
            # (charge-temp correction). delta_bt is in the display unit → °C/min.
            if delta_bt and timex:
                _pk = max((delta_bt[i] for i in range(min(len(delta_bt), len(timex)))
                           if 50.0 <= timex[i] <= 240.0), default=None)
                if _pk is not None:
                    _pk_c = _pk / 1.8 if self.mode == "F" else _pk
                    if 8.0 <= _pk_c <= 30.0:   # glitch guard (impossible RoR = sensor jump)
                        peak_ror_samples.append(_pk_c)

            # 2. Filter by Agtron Category
            _raw_color, _ = _selected_roast_color(self.lastprofiledata)
            agtron_plan = (to_agtron(_raw_color, self.lastprofiledata.get("color_system", ""))
                           if _raw_color is not None else 0.0)
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
                _a_dry, _a_mai, _a_dev = self._extract_phase_control(phase_times, 0)
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
                # Trajectoire DEV continue (même cohorte couleur-assortie)
                _traj = self._extract_dev_trajectory(phase_times)
                if _traj:
                    for _et, _pf in _traj.items():
                        for _f, _v in _pf.items():
                            dev_traj_samples[_et][_f].append(_v)
                # RoR au drop (même cohorte) : médiane du delta_bt sur les
                # 15 s précédant le DROP (robuste au retrait de sonde / spike
                # de fin). delta_bt est en unité d'affichage → °C/min.
                _drop_t = self.lastprofiledata.get("computed", {}).get("DROP_time", 0.0) or 0.0
                _drop_ror_c: "float | None" = None
                if _drop_t > 0.0 and delta_bt and timex:
                    _win = [delta_bt[i] for i in range(min(len(delta_bt), len(timex)))
                            if _drop_t - 15.0 <= timex[i] <= _drop_t
                            and delta_bt[i] is not None]
                    if _win:
                        _dr = float(np.median(_win))
                        _dr_c = _dr / 1.8 if self.mode == "F" else _dr
                        if 0.5 <= _dr_c <= 12.0:   # glitch guard (sensor jump)
                            drop_ror_samples_c.append(_dr_c)
                            _drop_ror_c = _dr_c

                # Complete P1 candidate. Phase timings, heater, airflow and the
                # development air trajectory must all come from this one roast.
                _dry_sec = float(phase_times.get("dry_end") or 0.0)
                _fc_sec = float(phase_times.get("fc_start") or 0.0)
                _drop_sec = float(phase_times.get("drop") or 0.0)
                _fc_profile_c = (fromFtoCstrict(float(_fc_log)) if _log_is_f else float(_fc_log)) if _fc_log > 0 else None
                _drop_profile_c = (fromFtoCstrict(float(_drop_log)) if _log_is_f else float(_drop_log)) if _drop_log > 0 else None
                # The THERMAL SKELETON: milestones in order, both
                # temperatures, and a readable rate of rise at the drop. This is
                # what a roast has to carry to say anything at all about where
                # this coffee cracks and finishes. A file failing it is
                # incomplete or malformed and stays out entirely — the quality
                # filters exist to catch bad data, not to demand richness.
                _has_skeleton = (_dry_sec > 0.0 and _fc_sec > _dry_sec
                                 and _drop_sec > _fc_sec
                                 and _fc_profile_c is not None
                                 and _drop_profile_c is not None
                                 and _drop_ror_c is not None)
                # The CONTROL HAND on top of it. Absent means the roast was
                # driven without logging the sliders (PID-only, or events never
                # recorded) — sparse, not broken. Measured on the living corpus:
                # 3 roasts of 74, and always both levers missing together.
                _has_controls = (None not in (_h_dry, _h_mai, _h_dev, _h_fc)
                                 and None not in (_a_dry, _a_mai, _a_dev)
                                 and _traj is not None and 0 in _traj)
                if _has_skeleton:
                    (coherent_profiles if _has_controls else skeleton_profiles).append({
                        "id": log.name,
                        "batch_g": _w_green,
                        "agtron": agtron_plan,
                        "color_basis": _color_basis,
                        "dry_time_min": _dry_sec / 60.0,
                        "maillard_time_min": (_fc_sec - _dry_sec) / 60.0,
                        "dev_time_min": (_drop_sec - _fc_sec) / 60.0,
                        "fc_bt_c": _fc_profile_c,
                        "drop_bt_c": _drop_profile_c,
                        "drop_ror_c": _drop_ror_c,
                        "heater_dry": _h_dry,
                        "heater_maillard": _h_mai,
                        "heater_dev": _h_dev,
                        "heater_fc": _h_fc,
                        "heater_de": _h_de,
                        "airflow_dry": _a_dry,
                        "airflow_maillard": _a_mai,
                        "airflow_dev": _a_dev,
                        "dev_trajectory": _traj or {},
                        "pre_de_descent": _descent,
                    })

        # ── FC linear regression by charge ────────────────────────────────
        # FC is correlated with initial charge temperature (higher charge → higher FC).
        # Learn FC = a × Charge + b coefficients; will be applied in generate_roast_plan.
        fc_regression_slope: float | None = None
        fc_regression_offset: float | None = None

        fc_regression = _fit_fc_charge_regression(
            charge_samples_c, fc_samples_c)
        fc_regression_slope = fc_regression["slope"]
        fc_regression_offset = fc_regression["offset"]
        _logd.info("RoastPlan: FC regression %s — %s", fc_regression["status"],
                   fc_regression["reason"])

        # Legacy descriptive aggregates are retained for diagnostics below.
        # P1 replaces every value consumed by the plan with one coherent roast.
        fc_bt_learned_c: float | None = (round(float(np.median(fc_samples_c)), 1)
                                         if fc_samples_c else None)
        timing_dry_learned: float | None = (round(float(np.median(dry_time_samples_min)), 2)
                                            if dry_time_samples_min else None)
        timing_fc_learned: float | None = (round(float(np.median(fc_time_samples_min)), 2)
                                           if fc_time_samples_min else None)
        _drop_basis = ("ground" if len(drop_color_samples_c["ground"]) >= 2 else "whole")
        _drop_samples = drop_color_samples_c[_drop_basis]
        drop_bt_learned_c: float | None = (round(float(np.median(_drop_samples)), 1)
                                           if len(_drop_samples) >= 2 else None)
        # Dispersions robustes (MAD) — mesurent la CONFIANCE de l'historique :
        # un grain régulier resserre les seuils du coach, un historique bruité
        # (jalons mal marqués, lots hétérogènes) les relâche (bloc tolérances).
        def _mad(samples: list[float]) -> "float | None":
            if len(samples) < 2:
                return None
            med = float(np.median(samples))
            return round(float(np.median([abs(s - med) for s in samples])), 2)
        fc_bt_mad_c   = _mad(fc_samples_c)
        drop_bt_mad_c = _mad(_drop_samples)
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
        heater_fc_learned = _med(heater_fc_samples)   # item C
        heater_de_learned = _med(heater_de_samples)
        pre_de_lead_learned = _med(pre_de_lead_samples)
        pre_de_step_learned = _med(pre_de_step_samples)
        peak_ror_learned = _med(peak_ror_samples)   # setup loop : pic médian du grain (°C/min)
        peak_ror_n = len(peak_ror_samples)
        # Trajectoire DEV apprise : médiane par (levier, fraction) + n min sur
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

        # ── P1 coherent historical block ────────────────────────────────────
        # Prefer a ground-colour cohort when it has at least two complete
        # observations; otherwise use whole-bean, never a pooled statistic.
        _target_mid = _mean(target_agtron.agtron_range.min_value,
                            target_agtron.agtron_range.max_value)
        _profile_selected, _profile_n, _profile_source, _profile_basis = (
            _choose_coherent_history(coherent_profiles, charge_weight_g, _target_mid))
        _profile_cohort = [p for p in coherent_profiles
                           if p.get("color_basis") == _profile_basis]

        # ── Graded fallback: the thermal skeleton alone ─────────────────────
        # LAST RESORT ONLY. With two or more complete profiles nothing below
        # runs, so a plan that already learns can never be degraded by a roast
        # that logged no sliders. Under that bar the plan is pure grid today —
        # yet these roasts still know where this coffee cracks and finishes,
        # and throwing that away because the operator's hand went unrecorded
        # discards evidence rather than protecting the plan from bad evidence.
        # The control settings stay on the grid: the skeleton says nothing
        # about them, and inventing a hand from another roast would rebuild the
        # very cross-roast mixing P1 exists to prevent.
        _skeleton_only = False
        if _profile_n < 2 and skeleton_profiles:
            _s_selected, _s_n, _s_source, _s_basis = _choose_coherent_history(
                coherent_profiles + skeleton_profiles, charge_weight_g, _target_mid)
            if _s_selected is not None and _s_n >= 2:
                _skeleton_only = True
                _profile_selected, _profile_n, _profile_basis = _s_selected, _s_n, _s_basis
                _profile_source = _PlanSource(_SRC_SKELETON, _s_n, f"skeleton (n={_s_n})")
                _profile_cohort = [p for p in coherent_profiles + skeleton_profiles
                                   if p.get("color_basis") == _profile_basis]
                _logd.info("RoastPlan: no complete profile — thermal skeleton from "
                           "%d roast(s) without logged controls; heater and airflow "
                           "stay on the grid", _s_n)

        _prediction_error_summary = summarize_prediction_errors(prediction_snapshots)

        # At n=2 the normal adoption policy blends this one real roast with the
        # grid. At n>=3 every learned field below comes from the same medoid.
        if _profile_selected is not None and _profile_n >= 2:
            fc_bt_learned_c = round(float(_profile_selected["fc_bt_c"]), 1)
            fc_samples_c = [float(p["fc_bt_c"]) for p in _profile_cohort]
            timing_dry_learned = round(float(_profile_selected["dry_time_min"]), 2)
            timing_fc_learned = round(
                float(_profile_selected["dry_time_min"])
                + float(_profile_selected["maillard_time_min"]), 2)
            dry_time_samples_min = [float(p["dry_time_min"]) for p in _profile_cohort]
            drop_bt_learned_c = round(float(_profile_selected["drop_bt_c"]), 1)
            _drop_samples = [float(p["drop_bt_c"]) for p in _profile_cohort]
            _drop_basis = str(_profile_basis)
            drop_ror_samples_c = [float(p["drop_ror_c"]) for p in _profile_cohort]
            # The control hand — only when the reference roast actually logged
            # one. On the skeleton tier every field below stays None, so each
            # consumer falls through to its grid base on its own guard and
            # reports "grid" as its source.
            if _skeleton_only:
                heater_dry_learned = heater_mai_learned = heater_dev_learned = None
                heater_fc_learned = heater_de_learned = None
                heater_samples = 0
                heater_fc_samples = []
                heater_de_samples = []
                dev_trajectory_learned = {}
                dev_traj_n = 0
                pre_de_lead_learned = pre_de_step_learned = None
                pre_de_lead_samples = []
            else:
                heater_dry_learned = round(float(_profile_selected["heater_dry"]), 1)
                heater_mai_learned = round(float(_profile_selected["heater_maillard"]), 1)
                heater_dev_learned = round(float(_profile_selected["heater_dev"]), 1)
                heater_fc_learned = round(float(_profile_selected["heater_fc"]), 1)
                heater_de_learned = (_profile_selected.get("heater_de"))
                heater_samples = _profile_n
                heater_fc_samples = [float(_profile_selected["heater_fc"])] * _profile_n
                heater_de_samples = ([float(heater_de_learned)] * _profile_n
                                      if heater_de_learned is not None else [])
                dev_trajectory_learned = copy.deepcopy(_profile_selected.get("dev_trajectory") or {})
                dev_traj_n = _profile_n if dev_trajectory_learned else 0
                _descent_selected = _profile_selected.get("pre_de_descent")
                if _descent_selected is not None:
                    pre_de_lead_learned = round(float(_descent_selected[0]), 1)
                    pre_de_step_learned = round(float(_descent_selected[1]), 1)
                    pre_de_lead_samples = [float(_descent_selected[0])] * _profile_n
                else:
                    pre_de_lead_learned = None
                    pre_de_step_learned = None
                    pre_de_lead_samples = []
            fc_bt_mad_c = _mad(fc_samples_c)
            drop_bt_mad_c = _mad(_drop_samples)
            _logd.info("RoastPlan: coherent history %s selected %s (%s colour)",
                       _profile_source, _profile_selected.get("id"), _profile_basis)
        else:
            # P1 fallback: zero or one complete observation cannot assemble a
            # learned plan. Keep the grid; expose the lone roast as reference.
            fc_bt_learned_c = None
            fc_samples_c = []
            timing_dry_learned = None
            timing_fc_learned = None
            dry_time_samples_min = []
            drop_bt_learned_c = None
            _drop_samples = []
            heater_dry_learned = heater_mai_learned = heater_dev_learned = None
            heater_fc_learned = heater_de_learned = None
            heater_samples = 0
            heater_fc_samples = []
            heater_de_samples = []
            dev_trajectory_learned = {}
            dev_traj_n = 0
            drop_ror_samples_c = []
            pre_de_lead_learned = pre_de_step_learned = None
            pre_de_lead_samples = []
            fc_bt_mad_c = drop_bt_mad_c = None

        if not relevant_logs_data:
            if (fc_bt_learned_c is None and timing_dry_learned is None
                    and drop_bt_learned_c is None and not _prediction_error_summary):
                return None
            # No log matches the target colour (no master curve possible), but
            # FC temperature / phase timings / colour response were still
            # learnable from other roast levels of the same bean.
            return {"notes": [], "actions": [], "graph": None,
                    "crashes": [], "flicks": [],
                    "fc_bt_learned_c": fc_bt_learned_c,
                    "fc_bt_samples": len(fc_samples_c),
                    "fc_regression_slope": fc_regression_slope,   # FC = a × Charge + b
                    "fc_regression_offset": fc_regression_offset,
                    "fc_regression": fc_regression,
                    "timing_dry_min_learned": timing_dry_learned,
                    "timing_fc_min_learned": timing_fc_learned,
                    "timing_samples": len(dry_time_samples_min),
                    "drop_bt_learned_c": drop_bt_learned_c,
                    "drop_bt_samples": len(_drop_samples),
                    "drop_color_basis": (_drop_basis if len(_drop_samples) >= 2 else None),
                    "coherent_profile": _profile_selected,
                    "coherent_profile_samples": _profile_n,
                    "coherent_profile_source": _profile_source.label,
                    "coherent_profile_key": _profile_source.key,
                    "coherent_profile_basis": _profile_basis,
                    "prediction_error_summary": _prediction_error_summary,
                    "fc_bt_mad_c": fc_bt_mad_c,
                    "drop_bt_mad_c": drop_bt_mad_c,
                    "dev_trajectory_learned": dev_trajectory_learned,
                    "dev_traj_samples": dev_traj_n,
                    "peak_ror_learned": peak_ror_learned,   # setup loop
                    "peak_ror_n": peak_ror_n}

        crashes_raw = []
        flicks_raw = []

        for data in relevant_logs_data: # arrays are from charge to drop only
            tx          = data["timex"]
            tp_idx      = data["tp_index"]    # plus de fuite de scope
            phase_times = data["phase_times"] # plus de fuite de scope
            drop_time   = phase_times["drop"]
            f, c = find_flicks_crashes(
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
            "fc_regression_slope": fc_regression_slope,   # FC = a × Charge + b
            "fc_regression_offset": fc_regression_offset,
            "fc_regression": fc_regression,
            "timing_dry_min_learned": timing_dry_learned,
            "timing_fc_min_learned": timing_fc_learned,
            "timing_samples": len(dry_time_samples_min),
            "drop_bt_learned_c": drop_bt_learned_c,
            "drop_bt_samples": len(_drop_samples),
            "drop_color_basis": (_drop_basis if len(_drop_samples) >= 2 else None),
            "coherent_profile": _profile_selected,
            "coherent_profile_samples": _profile_n,
            "coherent_profile_source": _profile_source.label,
            "coherent_profile_key": _profile_source.key,
            "coherent_profile_basis": _profile_basis,
            "prediction_error_summary": _prediction_error_summary,
            "fc_bt_mad_c": fc_bt_mad_c,
            "drop_bt_mad_c": drop_bt_mad_c,
            "heater_dry_learned": heater_dry_learned,
            "heater_mai_learned": heater_mai_learned,
            "heater_dev_learned": heater_dev_learned,
            "heater_samples": heater_samples,
            "heater_fc_learned": heater_fc_learned,        # item C
            "heater_fc_samples": len(heater_fc_samples),
            "heater_de_learned": heater_de_learned,
            "heater_de_samples": len(heater_de_samples),
            "pre_de_lead_learned": pre_de_lead_learned,
            "pre_de_step_learned": pre_de_step_learned,
            "pre_de_descent_samples": len(pre_de_lead_samples),
            "dev_trajectory_learned": dev_trajectory_learned,
            "dev_traj_samples": dev_traj_n,
            "peak_ror_learned": peak_ror_learned,   # setup loop
            "peak_ror_n": peak_ror_n,
            "drop_ror_learned_c": _med(drop_ror_samples_c),   # item A (Bench-Integration)
            "drop_ror_samples": len(drop_ror_samples_c),
            "airflow_dry_learned": (_profile_selected.get("airflow_dry")
                                     if _profile_selected is not None and _profile_n >= 2 else None),
            "airflow_mai_learned": (_profile_selected.get("airflow_maillard")
                                     if _profile_selected is not None and _profile_n >= 2 else None),
            "airflow_dev_learned": (_profile_selected.get("airflow_dev")
                                     if _profile_selected is not None and _profile_n >= 2 else None),
            "airflow_samples": (_profile_n if _profile_selected is not None else 0),
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
        moisture_pct: float = 0.0,  # bean moisture % (0.0 = not measured)
        nominal_weight_g: float = 500.0,  # roaster's reference batch weight
        heat_retention: float = 0.65,     # roaster heat_retention_index [0-1]
        tech: "_TechnologyProfile" = _TECH_GENERIC,   # profil technologie
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

        # ── 1. ROAST DEPTH BASELINE — bonnes pratiques par TYPE de machine ──────
        # Sans historique, le plan suit les bonnes pratiques par type de machine.
        # FIR/NIR droppent avec un RoR plus vif que les tambours classiques :
        # light 5,5 / dark 4,0 °C/min vs light 3,5 / dark 2,0.
        ROR_AT_DROP_DARK  = tech.ror_at_drop_dark
        ROR_AT_DROP_LIGHT = tech.ror_at_drop_light
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

        # ── 5. RESIDUAL WATER MASS ──────────────────────────────────────────────
        # Dense AND wet keeps its thermal inertia and holds its RoR to the end;
        # light AND dry loses its energy fast. Stacks with the density term above.
        if moisture_pct > 0.0:
            _moist_delta = moisture_pct - _MOISTURE_NEUTRAL
            moisture_adj = _clamp(_moist_delta, -_MOISTURE_POINTS_MAX,
                                  _MOISTURE_POINTS_MAX) * 0.12
            drop_ror += moisture_adj
            _logd.debug(
                f"Moisture correction: {moisture_pct:.1f}%, delta={_moist_delta:+.2f} pt, "
                f"adj={moisture_adj:+.3f}°C/min")

        # ── 6. FINAL BOUNDS ──────────────────────────────────────────────────────
        # Hard floor: RoR at drop must be positive (bean is still gaining heat
        # until it physically leaves the drum).
        # Hard ceiling: cannot exceed ror_dev_avg - 0.3 (must be decelerating
        # at least slightly — a flat or accelerating RoR at drop indicates
        # under-development, which we flag but still clamp).
        # Bande saine par technologie : rayonnement [3,5 ; 7,0], tambour 0,5.
        ROR_DROP_FLOOR   = tech.ror_drop_floor    # °C/min minimum (preferred)
        ROR_DROP_CEILING = ror_dev_avg - 0.3      # must be below dev average
        if tech.ror_drop_ceiling is not None:
            ROR_DROP_CEILING = min(ROR_DROP_CEILING, tech.ror_drop_ceiling)

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
    def _adopt_learned(grid_value: float, learned: float | None,
                       n: int) -> "tuple[float, _PlanSource]":
        """
        Politique d'adoption progressive UNIQUE pour tout paramètre appris de
        l'historique (FC, durées de phase…) : n>=3 → valeur cohérente telle
        quelle ; n==2 → blend 50/50 avec la chaîne grille ; sinon grille.
        Retourne (valeur, source). Le caller reste responsable des bornes de
        plausibilité (passer learned=None si hors bornes).
        """
        if learned is not None:
            if n >= 3:
                return learned, _PlanSource(_SRC_LEARNED, n, f"learned (n={n})")
            if n == 2:
                return ((learned + grid_value) / 2.0,
                        _PlanSource(_SRC_BLEND, n, "learned/grid blend (n=2)"))
        return grid_value, _SOURCE_GRID

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
                              mode: str, decay_k: float,
                              env_fc_entry_ror_c: "float | None" = None,
                              ) -> "tuple[float, str, str]":
        """Vérification RoR du Maillard (banc 2026-08-05).

        DERNIÈRE étape, strictement informative. `decay_k` is an empirical
        geometric fallback, not a stable machine property. Les durées sont déjà
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
        ## Le diagnostic garde la valeur GÉOMÉTRIQUE : c'est elle qui révèle une
        ## courbe intenable. Seule la valeur PUBLIÉE passe à la prescription.
        _mai_conflict: str = self._maillard_conflict(
            _r_de_c, ror_fc_c, _drop_required_pct, maillard_time_min)
        _ror_fc_geom_c: float = ror_fc_c
        ## Sous enveloppe, la pente d'arrivée au FC est PRESCRITE, pas déduite
        ## d'une décroissance géométrique : c'est elle qui décide de la couleur
        ## (entrer à 8 au lieu de 5 donne un medium, même avec 1:00 de dev).
        if env_fc_entry_ror_c is not None:
            if abs(_ror_fc_geom_c - env_fc_entry_ror_c) > 1.0:
                _logd.info(
                    f"RoastPlan: drawn curve arrives at first crack at "
                    f"{_ror_fc_geom_c:.1f}°C/min, envelope prescribes "
                    f"{env_fc_entry_ror_c:.1f}")
            ror_fc_c = env_fc_entry_ror_c
        note = ""
        if _mai_conflict:
            _logd.warning(
                f"RoastPlan: Maillard conflict [{_mai_conflict}] — R_DE {_r_de_c:.1f} → "
                f"R_FC {_ror_fc_geom_c:.1f}°C/min to cover {ma_bt_temperature:.1f}°C in "
                f"{maillard_time_min:.2f}min, burner down {_drop_required_pct:.0f}%. "
                f"The setup was wrong; the plan reports it and does not correct it.")
            note = {
                "acceleration": QApplication.translate(
                    "tilauscope_roast_plan",
                    "Geometry note: covering {0}°{1} in {2} of Maillard makes the reference curve rise. Compare it with the live rate of rise and consider the charge setup or Maillard duration."),
                "crash": QApplication.translate(
                    "tilauscope_roast_plan",
                    "Geometry note: the reference curve falls to {3}°{1}/min before first crack to cover {0}°{1} in {2}. Check the live rate of rise before changing the plan."),
                "illegible": QApplication.translate(
                    "tilauscope_roast_plan",
                    "Geometry note: the planned heater change is {4}% across a {2} Maillard. Treat this as an unusual reference shape and reassess it against live measurements."),
            }[_mai_conflict].format(
                f"{ma_bt_temperature * ror_scale:.0f}", mode,
                self.format_time(maillard_time_min),
                f"{_ror_fc_geom_c * ror_scale:.1f}", f"{_drop_required_pct:.0f}")
        return ror_fc_c, _mai_conflict, note

    @staticmethod
    def _resolve_plan_confidence(
            *, fc_source: "_PlanSource", timing_source: "_PlanSource",
            drop_source: "_PlanSource",
            fc_bt_mad_c: "float | None",
            soak_dcharge_c: float, soak_dheater_pct: int,
            minutes_since_last_drop: "float | None", ror_scale: float,
    ) -> "_PlanConfidence":
        """Descriptive history support and conservative tolerances.
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
        def _src_score(src: "_PlanSource") -> int:
            # Sur la CLÉ, jamais sur le libellé. « skeleton » vaut un demi-point
            # comme le blend : la cible thermique est apprise d'un roast réel, mais
            # le plan ne sait rien de la conduite qui l'a produite.
            if src.key in (_SRC_BLEND, _SRC_SKELETON):
                return 1
            return 2 if src.key == _SRC_LEARNED else 0
        _conf_score = _src_score(fc_source) + _src_score(timing_source) + _src_score(drop_source)
        _conf_level = ("grid only" if _conf_score == 0 else
                       "consistent history" if _conf_score >= 4 else "partial history")
        _fc_mad = fc_bt_mad_c
        if (_conf_level == "consistent history" and _fc_mad is not None
                and _fc_mad > 2.5):
            _conf_level = "partial history"
        # Un niveau, un facteur. Le plan grille relâche parce qu'il ne sait rien
        # de CE grain ; l'historique cohérent resserre parce qu'il en sait
        # quelque chose et que le suivi doit être d'autant plus strict. Le
        # ×0.8 avait disparu lors de la réécriture, laissant l'appris toléré
        # exactement comme le partiel — le niveau haut ne servait plus à rien.
        _tol_factor = {"grid only": 1.35, "partial history": 1.0,
                       "consistent history": 0.8}[_conf_level]
        _conf_display = {
            "grid only": QApplication.translate("tilauscope_roast_plan", "grid only"),
            "partial history": QApplication.translate("tilauscope_roast_plan", "partial history"),
            "consistent history": QApplication.translate("tilauscope_roast_plan", "consistent history"),
        }[_conf_level]
        _logd.info(f"RoastPlan: history support={_conf_level} (score={_conf_score}, "
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

    ## Loi de l'humidité du grain : répartition 75/25 des 11 kJ que coûte 1 point
    ## d'eau sur 400 g — l'essentiel passe par le TEMPS, le reste par le feu.
    ## Doctrine machine : « > 11 % = séchage plus long, ne pas forcer au feu ».
    _MOISTURE_DRY_TIME_MIN_PER_POINT: Final[float] = 0.40
    _MOISTURE_DRY_HEATER_PCT_PER_POINT: Final[float] = 0.9
    _MOISTURE_FC_HEATER_PCT_PER_POINT: Final[float] = 1.0
    _MOISTURE_MAILLARD_TIME_MIN_PER_POINT: Final[float] = 0.2

    @classmethod
    def _green_moisture_effect(cls, moisture: "_GreenPairValue") -> "_GreenMoistureEffect":
        """Deltas from the bean's water MASS, as a continuous law (spec §5).

        Signs are constant across the range — no lever turns at the neutral. The
        first-crack burner is one-sided upward (a dry bean has no momentum
        problem at the crack) and the Maillard body compensation one-sided
        downward (a wet bean already builds its own pressure).
        """
        if not moisture.known:
            return _GreenMoistureEffect()
        _n: float = moisture.value
        _effect = _GreenMoistureEffect(
            d_dry_time_min=cls._MOISTURE_DRY_TIME_MIN_PER_POINT * _n,
            d_heater_dry_pct=cls._MOISTURE_DRY_HEATER_PCT_PER_POINT * _n,
            d_heater_fc_pct=cls._MOISTURE_FC_HEATER_PCT_PER_POINT * max(0.0, _n),
            d_maillard_time_min=(cls._MOISTURE_MAILLARD_TIME_MIN_PER_POINT
                                 * max(0.0, -_n)),
        )
        _logd.debug(
            f"Green moisture [{moisture.label}]: {_n:+.2f} pt → "
            f"dry {_effect.d_dry_time_min:+.2f} min, dry heater "
            f"{_effect.d_heater_dry_pct:+.1f}%, FC heater "
            f"{_effect.d_heater_fc_pct:+.1f}%, Maillard "
            f"{_effect.d_maillard_time_min:+.2f} min")
        return _effect

    @staticmethod
    def _charge_setup(*, process_type_lower: str, varieties: str = "",
                       family_weight: float = 0.0,
                       moisture: "_GreenPairValue", structure: "_GreenPairValue",
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
        # ── Charge band by PROCESS ───────────────────────────────────────────
        # The process sets the band, in measured BT. Roast level, batch weight and
        # history do not touch the charge; bean/ambient modulation is capped below
        # at ±_CHARGE_MODULATION_MAX_C. Decaf is tested first (can co-occur with a
        # process word, e.g. "decaf washed").
        if "decaf" in process_type_lower or "decaffeinated" in process_type_lower:
            _process_key = "decaf"
        elif ("honey" in process_type_lower or "pulped natural" in process_type_lower
              or "wet hulled" in process_type_lower or "natural" in process_type_lower
              or "dry process" in process_type_lower or "anaerobic" in process_type_lower
              or "fermentation" in process_type_lower or "fermented" in process_type_lower
              or "carbonic" in process_type_lower or "maceration" in process_type_lower
              or "yeast" in process_type_lower):
            # Fermented/anaerobic processes group with the naturals: they carry
            # the same surface sugars from extended contact with the mucilage/fruit.
            _process_key = "natural"
        else:
            _process_key = "washed"
        _charge_band = (_CHARGE_FLOOR_C, _CHARGE_CEILING_BY_PROCESS[_process_key])

        ## ── Équation double : process ET famille (Hoos 2026) ────────────────
        ## charge = neutre + Δprocess + w · Δfamille (+ modulations, plus bas)
        ##
        ## Les deux termes ne sont PAS de même nature, et c'est ce qui interdit
        ## une moyenne pondérée : le PROCESS est un risque de surface, donc un
        ## plafond ; la FAMILLE est une intention de rythme, donc une cible. Le
        ## clamp plus bas fait gagner la sécurité sur la préférence — un Typica
        ## nature ne peut pas se charger comme un Typica lavé, ce qui est la
        ## bonne précédence et ce que dit Hoos (le process ajoute une couche
        ## sans effacer la génétique).
        ##
        ## Le poids `w` n'est pas une constante à régler : c'est la confiance
        ## dans l'identité génétique, la réserve que Hoos pose lui-même (20-25 %
        ## de pollinisation croisée, erreurs de pépinière). w = 0 ramène
        ## exactement au comportement antérieur, donc aucun roast dont la variété
        ## est inconnue ne change.
        ##
        ## Transmission MESURÉE (bench_charge_authority.py) : +0,41 °C de TP par
        ## °C de charge, soit ~2 s de séchage par °C — les ±4 °C valent ~15 s.
        ## Sens par famille DÉCLARÉ, pas appris : le corpus n'a ni assez de
        ## cultivars ni de signal qualité pour le valider.
        ## `_charge_nominal` reste le milieu de bande AVANT la famille : c'est
        ## lui qui alimente la régression FC. La famille est un prior DÉCLARÉ ;
        ## la régression est APPRISE sur des charges réellement pratiquées, et la
        ## décaler d'un prior ferait bouger une prédiction apprise au nom d'une
        ## variété saisie à la main.
        _charge_nominal: float = _CHARGE_NEUTRAL_C + _CHARGE_PROCESS_OFFSET_C[_process_key]
        _charge_temperature: float = _charge_nominal
        _family_name: str = ""
        _family_delta: float = 0.0
        _matched = match_variety_family(varieties)
        if _matched is not None and family_weight > 0.0:
            _family_name, _raw_delta = _matched
            _family_delta = family_weight * _raw_delta
            _charge_temperature += _family_delta
            _logd.info(
                f"RoastPlan: charge family {_family_name} {_raw_delta:+.0f}°C "
                f"x weight {family_weight:.2f} = {_family_delta:+.1f}°C")

        # ── Modulation by bean and ambient constants, capped ────────────────
        # Only a few degrees of authority: the band is the doctrine, these
        # constants brush around it. Batch weight is deliberately absent — not
        # because the mass does not matter, it dominates, but because the charge
        # is far too weak a lever to answer it. Measured on the corpus
        # (bench_charge_authority.py, n=56 since 2025-11): the charge moves the
        # turning point by +0.41 °C per degree while 100 g move it by -17 °C, so
        # compensating a 150 g swing would take +63 °C of charge, twice the range
        # the machine offers. Setting the charge from the batch size (Hoos) is a
        # gas-drum rule: there the preheated drum IS the energy store, while a
        # radiant electric feeds the batch from the element in real time. The
        # batch size is answered by the burner and the phase durations instead.
        # Each input is gated on a
        # plausibility window first (out-of-window readings contribute 0).
        # One term per physical quantity: the water MASS to heat and the STRUCTURE
        # to heat it through. The aw is deliberately absent — it says how easily
        # water leaves, not how much energy it costs, so it drives the airflow.
        # Ambient humidity is absent too: it does not act on the roast in
        # progress, it acts BETWEEN roasts by drifting the bean's aw in storage.
        def _plausible(value: "float | None", lo: float, hi: float, label: str) -> "float | None":
            # `None` is the "not measured" sentinel here, not 0.0 (which would make
            # a room genuinely at 0 °C unreadable).
            if value is None:
                return None
            if not (lo <= float(value) <= hi):
                _logd.warning(f"RoastPlan: {label} {float(value):.1f} out of plausible "
                              f"range [{lo:g}, {hi:g}] — ignored for the charge modulation")
                return None
            return float(value)

        _ambient_ok = _plausible(ambient_temp_c, -10.0, 60.0, "ambient temperature")

        # Water mass: the thermal buffer. Its 4.184 J/g·K protects the surface
        # from scorching while heat is pushed to the core, so a wetter bean takes
        # a hotter charge and a drier one a gentler charge, symmetrically.
        _mod_moisture = _CHARGE_C_PER_MOISTURE_POINT * moisture.value if moisture.known else 0.0
        _mod_ambient = (20.0 - _ambient_ok) * 0.2 if _ambient_ok is not None else 0.0
        _charge_modulation = _clamp(
            _mod_moisture + _mod_ambient,
            -_CHARGE_MODULATION_MAX_C, _CHARGE_MODULATION_MAX_C)
        charge_bt_temperature: float = _clamp(
            _charge_temperature + _charge_modulation, _charge_band[0], _charge_band[1])

        # Structure: a dense bean absorbs and demands more; a light one scorches.
        # Applied AFTER the band clamp, like the heat soak: the band encodes a
        # SURFACE risk (process sugars), the density a STRUCTURE one, and a dense
        # bean legitimately charges past what its process band alone allows.
        # Silent for the many beans inside the density dead band — the override
        # still exists, it simply has nothing to say between 680 and 740 g/L.
        _mod_structure = _clamp(
            _CHARGE_C_PER_STRUCTURE_INDEX * structure.value if structure.known else 0.0,
            -_CHARGE_STRUCTURE_MAX_C, _CHARGE_STRUCTURE_MAX_C)
        charge_bt_temperature = _clamp(charge_bt_temperature + _mod_structure,
                                       _CHARGE_ABSOLUTE_MIN_C, _CHARGE_ABSOLUTE_MAX_C)
        _logd.info(
            f"RoastPlan: charge {charge_bt_temperature:.1f}°C — band {_charge_band} "
            f"({process_type_lower or 'washed default'}), in-band modulation "
            f"{_charge_modulation:+.1f}°C (moisture {_mod_moisture:+.1f} [{moisture.label or 'absent'}], "
            f"ambient {_mod_ambient:+.1f}), structure {_mod_structure:+.1f} "
            f"[{structure.label or 'absent'}] out of band")

        # The charge is doctrine-driven: a small batch charges at the same
        # temperature, which is precisely what lets it reach a higher turning
        # point and dry faster.

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
            family_name=_family_name, family_delta_c=_family_delta,
            band=_charge_band, nominal_temperature_c=_charge_nominal,
            temperature_c=charge_bt_temperature, soak_dcharge_c=_soak_dcharge_c,
            soak_dheater_pct=_soak_dheater, soak_tau_min=_soak_tau)

    @staticmethod
    def _base_phase_durations(*, roast_constraints: RoasterBasicPlanPerPhase,
                               structure: "_GreenPairValue") -> "tuple[float, float, float]":
        """Nominal total/drying/development durations, before water-activity
        and cross-roast calibration are applied. Pure — depends only on
        roast_constraints. Returns (total_time_min, dry_time_min, dev_time_min).
        """
        # ── Phase timings anchored on TOTAL ──────────────────────────────────
        # Drying and development both come from their own grid band; Maillard is
        # the remainder of the total (the grid is self-consistent: total_time is
        # exactly the sum of the three phase bands). Drying share falls out of the
        # grid rather than being imposed: ~46% of the roast in Very Light down to
        # ~33% in Extremely Dark.
        total_time_min: float = _mean(roast_constraints.total_time[0], roast_constraints.total_time[1])
        # Water reaches the drying duration once, through _green_moisture_effect.
        dry_time_min: float = _mean(roast_constraints.drying_time[0],
                                    roast_constraints.drying_time[1])
        if structure.known:
            # A dense bean holds its steam longer, so it dries a touch slower.
            dry_time_min += _DRY_MIN_PER_STRUCTURE_INDEX * structure.value

        # Development is an absolute DURATION, taken from the professional band
        # for the target roast level — not derived from a DTR target. The ratio is
        # a consequence of the whole roast, reported below, never the driver
        # (same doctrine as the rate of rise: settings are the cause).
        dev_time_min: float = _mean(roast_constraints.development_time[0], roast_constraints.development_time[1])
        return total_time_min, dry_time_min, dev_time_min

    ## Plancher de séchage : ancre du Skywalker et son coefficient d'inertie.
    ## Le plancher d'une AUTRE machine se déduit de son propre coefficient — pas
    ## d'un champ de plus : `dev_thermal_inertia_factor` est justement là pour ça
    ## (rappel de Tilau, 2026-08-08). Une machine plus inerte met plus longtemps
    ## à chasser l'eau, à charge relative égale.
    _DRY_FLOOR_ANCHOR_MIN: Final[float] = 4.0    # 4:00 à charge optimale…
    _DRY_FLOOR_ANCHOR_INERTIA: Final[float] = 0.45   # …pour l'inertie du Skywalker
    _DRY_FLOOR_FIXED_SHARE: Final[float] = 0.55  # part indépendante de la masse

    ## Part de creux À LA MASSE NOMINALE de la machine, et sensibilité de cette
    ## part à l'écart RELATIF de charge. Mesurés le 2026-08-11 sur les 94 roasts
    ## exploitables du corpus Skywalker : creux = charge × (0,487 + 0,396 ×
    ## (masse − nominale) / nominale), MAE 5,1 °C, LOO 5,2 °C, biais nul.
    ## Le terme de masse est NORMALISÉ par la nominale de la machine, il est donc
    ## neutre en forme : contrôlé sur le Cormorant (nominale 450 g, roasts à
    ## 500 g), il prédit un creux de 0,531 pour 0,544 mesuré — 2,5 °C d'erreur,
    ## contre 18 °C pour la part fixe seule.
    ## ── Point de retournement : TABLE D'ANCRES, pas une formule ─────────────
    ## Une seule formule sur toute la plage extrapole hors du mesuré sans le
    ## dire. Comme pour une déviation de sonde, ce qui décrit la machine est un
    ## JEU DE CONSTANTES PAR PALIER, chacune traçable à sa mesure et à son n.
    ##
    ## ⚠️ Les ancres sont NEUTRES PAR MACHINE : un RATIO de masse (lot / nominal)
    ## vers une PART DE CREUX (1 − TP/charge). Une table en grammes absolus et en
    ## °C ne transférerait à aucun autre torréfacteur — la forme relative est ce
    ## qui laisse une loi mesurée ici servir une machine sur laquelle elle n'a
    ## pas été ajustée (validé sur le corpus Cormorant, nominal 450 g).
    ##
    ## Mesuré sur le corpus RÉCENT seul (depuis nov. 2025) : les cinq roasts de
    ## 300 g du corpus sont tous de l'ancienne méthode et donnaient un TP 12 °C
    ## trop bas — une table bâtie dessus aurait figé l'artefact.
    ##
    ## (ratio de masse, part de creux, n)
    _TP_DIP_ANCHORS: Final[tuple[tuple[float, float, int], ...]] = (
        (0.375, 0.2962,  3),   # 3 points seulement — plateau, pas une pente
        (0.625, 0.3155, 17),   # solide
        (0.875, 0.4386,  7),   # faible — à recharger quand le palier se remplit
        (1.000, 0.5014, 27),   # solide
    )
    ## Sous la première ancre : MAINTIEN PLAT. Le corpus y a trois roasts (100,
    ## 150 et 208 g) qui tombent tous vers la même part — le plateau est ce que
    ## les données disent, pas un renoncement.
    ##
    ## Au-dessus de la dernière : on PROLONGE avec la sensibilité validée plutôt
    ## que de maintenir plat. Deux raisons — au-dessus du nominal il existe une
    ## théorie (plus de masse, creux plus profond) et un point de validation
    ## EXTERNE (Cormorant à 500 g pour 450 nominal, part mesurée 0,544).
    ## ⚠️ Réserve : ce corpus-ci mesure 0,5365 au ratio 1,19 (n=2), soit une pente
    ## plus douce que 0,396. Deux points ne suffisent pas à renverser une loi
    ## validée sur une autre machine — à rouvrir quand le palier se remplit.
    _TP_DIP_MASS_SENSITIVITY: Final[float] = 0.396
    ## Bornes de sécurité : un lot absurde ne doit pas sortir le TP du tambour.
    ## ⚠️ Le minimum doit rester SOUS la plus basse ancre (0,2962), sinon il
    ## écrase le plateau mesuré : à 0,31 toute la plage de ratio ≤ 0,554 sortait
    ## un 0,31 plat et la table n'était jamais honorée en bas de palier.
    _TP_DIP_SHARE_MIN: Final[float] = 0.28
    _TP_DIP_SHARE_MAX: Final[float] = 0.65

    def _nominal_weight_g(self) -> float:
        """Masse nominale de la machine (g), 0.0 si elle n'est pas connue.

        Source unique : le contexte roaster, avec repli sur le cache posé par
        `generate_roast_plan`. Il y avait ici trois façons divergentes d'aller la
        chercher, dont une qui testait la présence du cache SUR LE CONTEXTE alors
        qu'il est posé sur le plan — elle retombait donc toujours sur un 500 g
        codé en dur, y compris pour une machine dont la nominale vaut 400.
        """
        _ctx = getattr(self, "_roaster_ctx", None)
        if _ctx is not None:
            try:
                return float(_ctx.nominal_weight_g)
            except (AttributeError, TypeError, ValueError):
                pass
        return float(getattr(self, "_nominal_weight_g_cache", 0.0) or 0.0)

    @classmethod
    def _tp_placeholder_c(cls, charge_temperature_c: float,
                          charge_weight_g: float = 0.0,
                          nominal_weight_g: float = 0.0) -> float:
        """Où la courbe est TRACÉE au point de retournement (°C). Placeholder :
        `replan_from_milestone(plan, "tp", ...)` le remplace par le vrai TP dès qu'il
        est observé (~1 min après charge), puis re-cale tout ce qui suit.

        Le TP suit la MASSE chargée (r = −0,75), pas la température de charge
        (r = +0,29) : un petit lot retourne beaucoup plus haut qu'un gros à
        température de charge égale.
        """
        _anchors = cls._TP_DIP_ANCHORS
        if charge_weight_g <= 0.0 or nominal_weight_g <= 0.0:
            ## Lot ou machine inconnus : l'ancre nominale, la mieux échantillonnée.
            ## Ancre la plus proche du nominal — pas une égalité flottante :
            ## une table re-mesurée à 0,999 lèverait StopIteration.
            _share = min(_anchors, key=lambda a: abs(a[0] - 1.0))[1]
        else:
            _ratio = charge_weight_g / nominal_weight_g
            if _ratio <= _anchors[0][0]:
                _share = _anchors[0][1]
            elif _ratio >= _anchors[-1][0]:
                _share = (_anchors[-1][1]
                          + cls._TP_DIP_MASS_SENSITIVITY * (_ratio - _anchors[-1][0]))
            else:
                _share = _anchors[-1][1]
                for (_r0, _s0, _), (_r1, _s1, _) in zip(_anchors, _anchors[1:]):
                    if _r0 <= _ratio <= _r1:
                        _share = _s0 + (_s1 - _s0) * (_ratio - _r0) / (_r1 - _r0)
                        break
        _share = _clamp(_share, cls._TP_DIP_SHARE_MIN, cls._TP_DIP_SHARE_MAX)
        return charge_temperature_c * (1.0 - _share)

    @classmethod
    def _dry_floor_min(cls, charge_weight_g: float, batch_optimal_g: float,
                       thermal_inertia: float = _DRY_FLOOR_ANCHOR_INERTIA) -> float:
        """Shortest drying the machine can physically reach, in minutes.

        ⚠️ Plancher d'ABSURDITÉ, PAS un style. Il borne ce que la machine peut
        faire BRÛLEUR À FOND ; la durée VISÉE appartient à la grille théorique
        (`drying_time`), qui doit tenir seule au démarrage à vide. Un garde-fou
        qui interdit une conduite réelle est un bug — c'est exactement le défaut
        corrigé ici : à 4:30 fixe, il bloquait un roast de référence de Tilau
        séché en 3:37 à 244 g.

        ⚠️ DEUX SITES D'APPEL, DEUX POUVOIRS DIFFÉRENTS — se lire ensemble,
        sinon chacun donne une fausse impression de l'autre :

        - `_envelope_timing` le reçoit BORNÉ à la durée que l'enveloppe vient
          de déduire. Il n'y rallonge donc jamais : il n'y sert qu'à empêcher
          une correction d'eau négative de descendre sous le réalisable, au
          moment même où le Maillard est calé sur le séchage.
        - `_calibrate_and_floor_phase_durations` l'applique ENSUITE, en plancher
          plein, sur la durée finale — enveloppe et apprentissage compris. C'est
          là que le garde-fou d'absurdité vit, et il RALLONGE : une durée sous
          le plancher est remontée et le total s'étend.

        Deux variables, aucune régression sur le corpus :

        1. **La charge relative** `charge / optimal_batch`. L'énergie à fournir
           suit la masse de grain, la puissance disponible non — un petit lot
           sèche donc plus vite. La part fixe (55 %) est le coût de chauffe du
           tambour lui-même, qui ne disparaît pas quand il est presque vide.
        2. **L'inertie de la machine** `dev_thermal_inertia_factor`, en linéaire
           sur l'ancre. Skywalker 0.45 → 4:00 à charge optimale ; une machine
           deux fois plus inerte met deux fois plus longtemps.

        ANCRES TILAU (2026-08-08) sur Skywalker, brûleur à 100 % :
          - 150-200 g : « ça peut très bien sécher en 3:00 »
          - 400 g : « la puissance de la lampe est incapable de sécher en 3:30 »
        Les deux IMPOSENT cette pente : une loi plus plate ne peut pas les
        relier. Donne 175 g → 2:59, 250 g → 3:20, 400 g → 4:00, 450 g → 4:14.

        ⚠️ Le 3:00 est donné à 100 % alors que le Skywalker est bridé à
        `heater_max_pct` = 80 % (au-delà l'élément s'use prématurément). Le
        plancher est donc DÉLIBÉRÉMENT sous ce que le plan prescrira jamais.
        """
        _anchor = (cls._DRY_FLOOR_ANCHOR_MIN
                   * _clamp(thermal_inertia, 0.05, 1.0) / cls._DRY_FLOOR_ANCHOR_INERTIA)
        if batch_optimal_g <= 0.0:
            return _anchor
        _load = _clamp(charge_weight_g / batch_optimal_g, 0.0, 2.0)
        return _anchor * (cls._DRY_FLOOR_FIXED_SHARE
                          + (1.0 - cls._DRY_FLOOR_FIXED_SHARE) * _load)

    ## Le grain ne déplace le pic que de ±6 % (médianes par grain 15,3-17,3 sur
    ## une machine à 16,2) quand la machine le déplace de 30 % (16,2 vs 21,1).
    ## Bande SYMÉTRIQUE : un grain peut légitimement dépasser la médiane machine.
    _BEAN_CEILING_BAND: Final[float] = 0.10
    ## Sur les 6 scénarios golden, la moyenne du RoR planifié entre TP et DRY END
    ## vaut 0,74 à 0,77 de son pic — régularité de forme de la courbe, mesurée.
    _PEAK_TO_MEAN_RATIO: Final[float] = 0.75

    def _resolve_peak_ror_ceiling(self, machine_ceiling_c: float,
                                  peak_ror_learned: "float | None", peak_ror_n: int,
                                  charge_weight_g: float) -> "tuple[float, str]":
        """Peak RoR the planned curve may not exceed (°C/min), and its source.

        The MACHINE sets the level, the bean only modulates it — measured, not
        assumed (see _BEAN_CEILING_BAND). The learned peak is therefore adopted
        with the usual policy but clamped into a ±10 % band around the machine
        value, so a bean that merely happens to have been roasted gently can
        never be mistaken for a physical limit.

        Small batches are learned from like any other; the ±10 % band is the
        only guard needed.
        """
        if peak_ror_learned is None or peak_ror_n < 2:
            return machine_ceiling_c, "machine"
        _adopted, _src = self._adopt_learned(machine_ceiling_c, float(peak_ror_learned),
                                             peak_ror_n)
        _lo = machine_ceiling_c * (1.0 - self._BEAN_CEILING_BAND)
        _hi = machine_ceiling_c * (1.0 + self._BEAN_CEILING_BAND)
        return _clamp(_adopted, _lo, _hi), _src.label

    @classmethod
    def _dry_floor_from_ceiling(cls, tp_time_min: float, bt_dry_end_c: float,
                                bt_tp_c: float, ceiling_c: float) -> float:
        """Shortest drying the ceiling allows, in minutes.

        The machine cannot climb from the turning point to the dry end faster
        than its peak allows, and the planned curve's MEAN over that stretch is
        a stable fraction of its peak (_PEAK_TO_MEAN_RATIO). Inverting that gives
        the floor analytically — no need to build the curve and iterate.

        Validated against the living corpus: at >= 375 g the formula predicts
        5:35 where 60 real Skywalker roasts dry in 5:42 (median).
        """
        _rise = bt_dry_end_c - bt_tp_c
        _mean_ok = cls._PEAK_TO_MEAN_RATIO * ceiling_c
        if _rise <= 0.0 or _mean_ok <= 0.0:
            return 0.0
        return tp_time_min + _rise / _mean_ok

    ## Part maximale du séchage que le Maillard peut occuper. Ancres Tilau :
    ## 4/3/1 → 0,75 et 5/4/1 → 0,80 sont réalistes, 3/3/1 ne l'est pas. Le corpus
    ## (92 roasts SW) mesure 0,69 en médiane, quartile haut 0,77 : 0,80 est donc
    ## le bord haut du réel, un PLAFOND et non une cible — l'enveloppe passe
    ## sous lui d'elle-même dès que le lot est gros.
    _MAILLARD_TO_DRYING_MAX: Final[float] = 0.80

    ## Décalage maximal du DRY END quand la courbe ne peut pas rester descendante
    ## autrement. Borné par le relevé : DRY END médian 149,2 °C en clair, quartile
    ## haut 151, contre 147 de grille — au-delà de 4 °C on quitterait le mesuré.
    _DRY_END_SHIFT_MAX_C: Final[float] = 4.0

    ## La descente doit être franche, pas juste non-croissante : viser l'égalité
    ## laisse les deux pentes au même chiffre une fois arrondies sur le plan.
    _DESCENT_MARGIN: Final[float] = 0.95

    ## ── Pente moyenne du séchage : loi de MONTÉE, pas constante ──────────────
    ## L'enveloppe prêtait à toute fournée la moyenne de ses deux premiers
    ## points, (16+12)/2 = 14 °C/min. La machine ne fait pas ça : mesuré par
    ## bande de masse, 13,5 au-dessus de 380 g mais 10,3 entre 200 et 260 g.
    ## Physiquement, une petite fournée retourne HAUT (TP 119 °C contre 93) donc
    ## elle démarre déjà dans la partie décroissante de la courbe — elle ne voit
    ## jamais le pic post-TP que l'enveloppe lui prête. Ce pic est une géométrie
    ## de GROSSE fournée.
    ##
    ## La grandeur qui la décrit est la MONTÉE à couvrir, que le plan connaît
    ## déjà : plus le trajet est long, plus la moyenne est haute, parce qu'un
    ## long trajet part d'un TP bas où le pic est réellement disponible.
    ## Ajusté sur le corpus récent (n=56, depuis nov. 2025) : R² 0,53, r +0,73.
    ##
    ## ⚠️ La boucle n'est PAS fermée ici, et c'est l'écart qui le prouve : le plan
    ## PRESCRIT la durée de séchage, donc si elle était tenue la pente réalisée
    ## vaudrait 14. Elle vaut 10,3 à 250 g. Le plan n'est pas atteint, et l'écart
    ## croît de façon monotone quand la fournée diminue — un écho ne ferait pas ça.
    ##
    ## Ne porte QUE sur le séchage : c'est ce qui a été mesuré. Mettre toute
    ## l'enveloppe à cette échelle a été essayé et donne 15:31 sur 250 g.
    _DRY_ROR_RISE_INTERCEPT: Final[float] = 6.79
    _DRY_ROR_PER_RISE_C: Final[float] = 0.110
    ## Garde-fou bas : sous ce niveau la pente ne décrit plus un séchage.
    _DRY_ROR_MIN_C: Final[float] = 6.0

    @classmethod
    def _envelope_timing(cls, *, envelope: "tuple[float, float, float, float]",
                         tp_time_min: float, tp_bt_c: float, dry_bt_c: float,
                         fc_bt_c: float, dev_time_min: float,
                         drop_ror_c: float,
                         dry_correction_min: float = 0.0,
                         dry_floor_min: float = 0.0) -> "_EnvelopeTiming":
        """Phase durations DEDUCED from the RoR envelope (lot 4).

        The envelope is the constraint and the durations are its consequence,
        the reverse of the style grid: a curve that must leave the turning
        point at 16 °C/min and reach the dry end at 12 takes exactly as long
        as the climb it has to make. Nothing here is fitted — it is the
        arithmetic of a slope and a temperature rise.

        Maillard is integrated in two segments because the envelope bends
        inside it: the last minute before first crack is the 8 → entry stretch,
        the rest is 12 → 8.
        """
        _post_tp, _de, _pre_fc, _at_fc = envelope
        _dry_rise: float = dry_bt_c - tp_bt_c
        ## Pente moyenne du séchage : loi de montée, plafonnée par la moyenne de
        ## l'enveloppe. Le plafond ne mord pas sur les montées observées (60 °C
        ## donne 13,4 contre 14) — c'est un filet, pour que la loi ne puisse
        ## jamais demander à la machine plus que ce que l'enveloppe promet.
        ## Le plafond gagne sur le plancher : `_clamp` rend `lo` quand lo > hi,
        ## donc un plancher figé à 6 sortirait au-dessus du plafond sur une
        ## machine dont l'enveloppe moyenne descend sous 6 °C/min — le garde-fou
        ## demanderait alors plus que ce que l'enveloppe promet, l'inverse de
        ## son rôle.
        _dry_ror_cap: float = (_post_tp + _de) / 2.0
        _dry_ror: float = _clamp(
            cls._DRY_ROR_RISE_INTERCEPT + cls._DRY_ROR_PER_RISE_C * max(0.0, _dry_rise),
            min(cls._DRY_ROR_MIN_C, _dry_ror_cap), _dry_ror_cap)
        _dry_time: float = (tp_time_min + _dry_rise / _dry_ror
                            if _dry_rise > 0.0 and _dry_ror > 0.0 else tp_time_min)
        ## Corrections eau/ambiante ET plancher machine entrent ICI, pas après :
        ## appliqués en aval, ils déplaçaient le séchage sur lequel on venait
        ## justement de caler le Maillard.
        ## Le plancher ne peut pas dépasser l'attente : c'est un MINIMUM, et un
        ## minimum au-dessus de ce que la machine fait en moyenne est une
        ## contradiction. Il est calibré sur 0,75 × plafond (12 °C/min) quand la
        ## loi de montée en donne 13,9 sur une grosse fournée — il allongeait
        ## alors le séchage de 45 s au lieu de le garder. Borné ICI, il retrouve
        ## son rôle : rattraper une correction d'eau trop courte, jamais rallonger.
        ##
        ## ⚠️ Ce bornage vaut pour CE site seulement. Le garde-fou d'absurdité
        ## n'est pas perdu : `_calibrate_and_floor_phase_durations` réapplique le
        ## MÊME plancher, non borné, sur la durée finale, après l'enveloppe et
        ## après l'apprentissage. Une durée physiquement hors d'atteinte y est
        ## toujours remontée.
        _dry_floor_min = min(dry_floor_min, _dry_time)
        _dry_time = max(tp_time_min, _dry_time + dry_correction_min, _dry_floor_min)
        if _dry_rise > 0.0 and _dry_time > tp_time_min:
            _dry_ror = _dry_rise / (_dry_time - tp_time_min)

        _mai_rise: float = fc_bt_c - dry_bt_c
        _last_min_c: float = (_pre_fc + _at_fc) / 2.0    # °C covered in the last minute
        if _mai_rise <= 0.0:
            _mai_time: float = 0.0
        elif _mai_rise <= _last_min_c:
            _mai_time = _mai_rise / _last_min_c
        else:
            _mai_time = 1.0 + (_mai_rise - _last_min_c) / ((_de + _pre_fc) / 2.0)
        ## LOI MACHINE (Tilau) : le Maillard est TOUJOURS PLUS COURT que le
        ## séchage, pas seulement « pas plus long » — 4/3/1, 5/4/1 ; 3/3/1 est
        ## impossible, le RoR n'a pas le temps de descendre. C'est un RAPPORT,
        ## d'où _MAILLARD_TO_DRYING_MAX, et non une simple comparaison.
        ## C'est le MAILLARD qui cède. Le séchage a une ancre de DURÉE tenue par
        ## la masse (3:00 à 150 g, 4:00 à 400 g, `_dry_floor_min`, tenue en aval
        ## par `_calibrate_and_floor_phase_durations` et non ici) ; le Maillard
        ## n'en a pas — il n'a qu'une enveloppe, et une enveloppe se resserre.
        ## Rallonger le séchage pour couvrir un Maillard trop long donnait 4:50 de
        ## séchage sur 150 g, deux fois le roast réel.
        ## Dernier recours seulement : si le Maillard resserré exigeait une pente
        ## MOYENNE au-dessus du pic post-TP, la machine ne sait pas le faire et
        ## c'est le séchage qui s'allonge, juste assez pour rétablir le rapport.
        ## Une courbe de RoR DESCEND : la pente moyenne du Maillard ne peut pas
        ## dépasser celle du séchage. Quand le plancher machine allonge le
        ## séchage sans lui donner de °C en plus, sa moyenne s'effondre et le
        ## Maillard resserré passe au-dessus — physiquement impossible.
        ## La seule variable libre est alors le DRY END : sécher plus longtemps
        ## à la même pente, c'est arriver plus haut. On le décale du strict
        ## nécessaire pour que les deux lois tiennent ensemble.
        ## Vérification indépendante : à 250 g le calcul demande 148,4 °C, et les
        ## 91 roasts SW marquent le DRY END à 149,2 en médiane sur les torréfactions
        ## claires (IQR 147-151). Physique et corpus tombent sur le même chiffre.
        _dry_shift: float = 0.0
        _cap_raw: float = _dry_time * cls._MAILLARD_TO_DRYING_MAX
        _k: float = cls._DESCENT_MARGIN
        _mai_floor: float = (_mai_rise / (_dry_ror * _k) if _dry_ror > 0.0 else 0.0)
        if _mai_floor > _cap_raw > 0.0 and _dry_time > tp_time_min:
            ## (fc − de − d) / cap = k · (de + d − tp) / t_actif  →  linéaire en d
            _active: float = _dry_time - tp_time_min
            _denom: float = _k * _cap_raw + _active
            if _denom > 0.0:
                _dry_shift = _clamp(
                    (_mai_rise * _active - _k * _dry_rise * _cap_raw) / _denom,
                    0.0, cls._DRY_END_SHIFT_MAX_C)
                _dry_rise += _dry_shift
                _mai_rise -= _dry_shift
                _dry_ror = _dry_rise / _active
                _mai_time = (1.0 + (_mai_rise - _last_min_c) / ((_de + _pre_fc) / 2.0)
                             if _mai_rise > _last_min_c
                             else max(0.0, _mai_rise) / _last_min_c)

        _dry_stretched: bool = False
        _mai_compressed: bool = False
        _mai_cap: float = _dry_time * cls._MAILLARD_TO_DRYING_MAX
        if _mai_time > _mai_cap > 0.0:
            ## Resserrer le Maillard remonte TOUTE l'enveloppe, dernière minute
            ## comprise : la pente à comparer au pic est donc la moyenne obtenue.
            if _mai_rise / _mai_cap <= _post_tp:
                _mai_compressed = True
                _mai_time = _mai_cap
            else:
                _dry_stretched = True
                _dry_time = _mai_time / cls._MAILLARD_TO_DRYING_MAX
                if _dry_rise > 0.0 and _dry_time > tp_time_min:
                    _dry_ror = _dry_rise / (_dry_time - tp_time_min)
        _mai_ror: float = _mai_rise / _mai_time if _mai_time > 0.0 else _de

        ## Le développement garde sa DURÉE (bande de niveau, lot 3) ; c'est son
        ## ΔT qui se déduit, en descendant de l'entrée FC vers le RoR de drop.
        _dev_delta: float = max(0.0, (_at_fc + max(0.0, drop_ror_c)) / 2.0
                                * max(0.0, dev_time_min))
        return _EnvelopeTiming(
            dry_time_min=_dry_time, maillard_time_min=_mai_time,
            dry_ror_c=_dry_ror, maillard_ror_c=_mai_ror,
            fc_entry_ror_c=_at_fc, dev_delta_c=_dev_delta,
            drying_stretched=_dry_stretched,
            maillard_compressed=_mai_compressed,
            dry_bt_shift_c=_dry_shift)

    def _calibrate_and_floor_phase_durations(
            self, *, dry_time_min: float, total_time_min: float, dev_time_min: float,
            drying_time_band: "tuple[float, float]", maillard_time_band: "tuple[float, float]",
            t_dry_raw: "float | None", t_fc_raw: "float | None", t_n: int,
            coherent_source: "_PlanSource | None" = None,
            charge_weight_g: float = 0.0, batch_optimal_g: float = 0.0,
            thermal_inertia: float = _DRY_FLOOR_ANCHOR_INERTIA,
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
        # Realized phase timings from the coherent historical reference roast.
        # Descriptive part: the planned durations follow the machine's real
        # behaviour, clamped to the grid style window ±0.5 min so the plan
        # stays within professional canons (adoption policy identical to the
        # learned FC: n>=3 medoid profile, n==2 blend 50/50 with the adjusted grid).
        # Prescriptive part: when the RAW learned duration sits outside the
        # strict style window, nudge the phase heater (bounded ±5%, 3%/min,
        # n>=3 only) to close the physical gap — and tell the user why.
        maillard_time_min: float = max(2.0, total_time_min - dry_time_min - dev_time_min)
        timing_source: "_PlanSource" = _SOURCE_GRID
        _cal_heater_dry: float = 0.0
        _cal_heater_mai: float = 0.0
        _notes: list[str] = []
        if (t_dry_raw is not None and t_fc_raw is not None and t_n >= 2
                and 2.5 <= t_dry_raw <= 8.0
                and 2.0 <= (t_fc_raw - t_dry_raw) <= 7.0):
            _mai_raw = t_fc_raw - t_dry_raw
            _WINDOW_MARGIN = 0.5   # legacy independent-history personalization
            _dry_cal = (t_dry_raw if coherent_source else
                        _clamp(t_dry_raw, drying_time_band[0] - _WINDOW_MARGIN,
                               drying_time_band[1] + _WINDOW_MARGIN))
            _mai_cal = (_mai_raw if coherent_source else
                        _clamp(_mai_raw, maillard_time_band[0] - _WINDOW_MARGIN,
                               maillard_time_band[1] + _WINDOW_MARGIN))
            # Shared progressive-adoption policy (same as the learned FC).
            dry_time_min, timing_source = self._adopt_learned(dry_time_min, _dry_cal, t_n)
            maillard_time_min, _        = self._adopt_learned(maillard_time_min, _mai_cal, t_n)
            if coherent_source:
                timing_source = coherent_source
            _logd.info(
                f"RoastPlan: phase timing from history dry={dry_time_min:.2f}min "
                f"maillard={maillard_time_min:.2f}min [{timing_source}]")
            if t_n >= 3 and not coherent_source:
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

        # ── Contrôles techniques de plausibilité des durées ──────────────────
        # Ils viennent de la MACHINE, pas de la grille de style, donc ils passent
        # APRÈS la calibration apprise : sa fenêtre d'adoption laisse entrer un
        # séchage de 2,5 min, physiquement hors d'atteinte sur un tambour de cette
        # taille (c'est le domaine des torréfacteurs d'échantillon).
        # Chaque phase est bornée SÉPARÉMENT, jamais l'une aux dépens de l'autre :
        # le total est la somme des trois (calculé plus bas), donc c'est LUI qui
        # s'allonge quand un garde-fou mord. Recalculer le Maillard par
        # soustraction ici écraserait la durée apprise de l'historique.
        # ⚠️ C'EST ICI que le plancher de séchage rallonge — `_envelope_timing`
        # reçoit le même chiffre mais borné à la durée déduite, donc il n'y peut
        # que retenir, jamais étendre. Ce bloc-ci est le garde-fou d'absurdité.
        # ⚠️ Le plancher de séchage DÉPEND DU POIDS depuis le 2026-08-08 : voir
        # _dry_floor_min. Il valait 4,5 min en dur, ce qui le rendait faux aux
        # deux bouts — trop contraignant sur un petit lot (il écrasait jusqu'à la
        # durée APPRISE de l'historique sur les niveaux clairs, dont la fenêtre
        # d'adoption plafonne elle aussi à 4,5), et trop permissif nulle part
        # puisque la durée des phases ne lisait pas le poids du tout.
        _DRY_MIN_MIN: float = self._dry_floor_min(charge_weight_g, batch_optimal_g,
                                                  thermal_inertia)
        _MAI_MIN_MIN: float = 2.0    # data-quality guard, not a roasting law
        if dry_time_min < _DRY_MIN_MIN:
            _logd.warning(
                f"RoastPlan: planned drying {dry_time_min:.2f}min is below the "
                f"machine floor {_DRY_MIN_MIN:.2f}min — raised; the total extends")
            dry_time_min = _DRY_MIN_MIN
        if maillard_time_min < _MAI_MIN_MIN:
            _logd.warning(
                f"RoastPlan: planned Maillard {maillard_time_min:.2f}min is below "
                f"the data plausibility limit {_MAI_MIN_MIN:.2f}min — raised")
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
            density: float, moisture_pct: float, nominal_weight_g: float,
            heat_retention: float, tech: "_TechnologyProfile",
            coherent_source: "_PlanSource | None" = None,
            env_dev_delta_c: "float | None" = None,
            env_fc_entry_ror_c: "float | None" = None,
    ) -> "_DropAndDevRor":
        """Learned-drop adoption from measured colours, the FC→DROP coherence
        rebuild, and the development/drop RoR derivation (banc 2026-08-05).

        Pure: takes the grid+inertia drop estimate and the style band, returns
        the final drop BT and its source, the development RoR, the RoR at
        drop, and the operator notes for the caller to append to
        history["actions"] — exactly like _verify_maillard_ror's note.
        """
        # ── Learned drop from measured colours (design validé 2026-07-04) ───
        # When the bean's history carries measured colours, the coherent
        # reference roast's drop BT, corrected to the current target colour,
        # REPLACES the grid+inertia
        # estimate (same progressive-adoption policy as the learned FC).
        # Clamped to the style band ±3 °C: a biased history (moved probe,
        # atypical lot) can never pull the plan out of the target style.
        drop_source: "_PlanSource" = _SOURCE_GRID
        _notes: "list[str]" = []
        ## Lot 4 — sous enveloppe, la température de drop se DÉDUIT : on entre
        ## le FC à la pente prescrite, elle continue de descendre vers le RoR de
        ## drop, et le ΔT qui en résulte donne la cible. La bande de style ne la
        ## fixe plus (aucune pente drop/Agtron universelle n'est validée) ; les
        ## couleurs MESURÉES de l'historique, elles, la corrigent toujours.
        if env_dev_delta_c is not None:
            _env_drop = round(fc_bt + env_dev_delta_c, 1)
            if abs(_env_drop - drop_bt_temperature) > 0.05:
                _logd.info(
                    f"RoastPlan: drop from envelope {_env_drop:.1f}°C "
                    f"(grid {drop_bt_temperature:.1f}°C) — FC {fc_bt:.1f}°C plus "
                    f"{env_dev_delta_c:.1f}°C over {dev_time_min:.2f} min")
            drop_bt_temperature = _env_drop
        _colour_note: "str | None" = None
        _colour_drop_c: "float | None" = None
        _drop_raw = drop_learned_c
        _drop_n   = int(drop_samples or 0)
        if _drop_raw is not None and (drop_min - 8.0) <= float(_drop_raw) <= (drop_max + 8.0):
            _drop_cal  = _clamp(float(_drop_raw), drop_min - 3.0, drop_max + 3.0)
            _drop_grid = drop_bt_temperature
            drop_bt_temperature, drop_source = self._adopt_learned(
                drop_bt_temperature, _drop_cal, _drop_n)
            if not drop_source.is_grid and coherent_source:
                drop_source = coherent_source
            if not drop_source.is_grid:
                # Held back, not appended: the FC→DROP coherence rebuild below
                # can still overrule this target. Emitting here left the
                # operator reading "the colour history moved the drop to X"
                # under a printed target several degrees the other way — the
                # sentence that carries the reasoning contradicting the figure
                # it is supposed to explain.
                _colour_note = QApplication.translate(
                    "tilauscope_roast_plan",
                    "Colour feedback ({0} measured roast(s)): drop target adjusted {1}°C vs grid ({2}°)").format(
                    _drop_n, f"{drop_bt_temperature - _drop_grid:+.1f}", f"{_drop_grid:.1f}")
                _colour_drop_c = drop_bt_temperature
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
            drop_source = _PlanSource(_SRC_COHERENCE, 0, "coherence")
            # The colour target did not survive: say what actually decided — the
            # learned first crack sits high for this roast level, so the drop
            # follows it, not the colour target.
            if _colour_note is not None and _colour_drop_c is not None:
                _colour_note = QApplication.translate(
                    "tilauscope_roast_plan",
                    "The measured colours of your last {0} roast(s) put the drop at {1}°, but the learned first crack ({2}°) is high for this roast level: reaching it over the planned development lifts the target to {3}°.").format(
                    _drop_n, f"{_colour_drop_c:.1f}", f"{fc_bt:.1f}",
                    f"{drop_bt_temperature:.1f}")

        if _colour_note is not None:
            _notes.append(_colour_note)

        # GEOMETRY-DERIVED development average RoR: the real slope between the FC
        # and drop anchors over the development duration. Single value used both
        # for display and to place the pre-drop waypoint, so the dev segment is
        # self-consistent (no kink, no displayed/actual mismatch). °C/min.
        dev_ror:float = (drop_bt_temperature - fc_bt) / dev_time_min if dev_time_min > 0 else dev_ror_expected
        # Floor at the theoretical minimum development slope.
        dev_ror = max(_dev_ror_floor, dev_ror)
        ## Le développement DESCEND. Une moyenne au-dessus de la pente d'entrée
        ## FC décrit une courbe qui remonte après le crack — c'est l'incohérence
        ## que le lot 4 refuse de laisser passer silencieusement.
        if env_fc_entry_ror_c is not None and dev_ror > env_fc_entry_ror_c + 0.1:
            _logd.warning(
                f"RoastPlan: development average {dev_ror:.1f}°C/min exceeds the "
                f"first-crack entry slope {env_fc_entry_ror_c:.1f} — the curve would "
                f"accelerate after the crack (drop {drop_bt_temperature:.1f}°C, "
                f"FC {fc_bt:.1f}°C over {dev_time_min:.2f} min)")
            _notes.append(QApplication.translate(
                "tilauscope_roast_plan",
                "The planned drop temperature asks development to speed up after first crack ({0} against {1}°/min entering the crack). Either drop earlier or enter the crack with more momentum.").format(
                f"{dev_ror:.1f}", f"{env_fc_entry_ror_c:.1f}"))

        drop_ror = self._compute_ror_at_drop(
            agtron_ratio    = agtron_ratio,
            dev_time_min           = dev_time_min,
            ror_dev_avg     = dev_ror,
            fc_bt         = fc_bt,
            drop_bt_temperature       = drop_bt_temperature,
            charge_weight   = charge_weight,
            density         = density,
            moisture_pct    = moisture_pct,
            nominal_weight_g= nominal_weight_g,        # Point 2+4: roaster-aware nominal
            heat_retention   = heat_retention,          # Point 4: thermal index
            tech            = tech,
        )
        # ── RoR au drop APPRIS de l'historique du grain (item A, Bench-Integration)
        # Cohorte couleur-assortie, profil cohérent, politique _adopt_learned habituelle
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
        if not drop_ror_source.is_grid:
            if coherent_source:
                drop_ror_source = coherent_source
            _logd.info(f"RoastPlan: drop RoR from history {drop_ror:.2f}°C/min "
                       f"[{drop_ror_source}] (n={_dror_n})")

        return _DropAndDevRor(
            drop_bt_temperature=drop_bt_temperature, drop_source=drop_source,
            dev_ror=dev_ror, drop_ror=drop_ror, drop_ror_source=drop_ror_source,
            notes=_notes)

    def _resolve_burner_setpoints(
            self, *, moisture: "_GreenPairValue", structure: "_GreenPairValue",
            moisture_fc_heater_pct: float,
            is_light_roast: bool, tech: "_TechnologyProfile", agtron_mean: float,
            process_type_lower: str, process_type: str,
            bean_varieties: str, bean_country: str,
            ambient_temp_c: "float | None",
            roast_constraints: RoasterBasicPlanPerPhase,
            cal_heater_dry_pct: float, cal_heater_mai_pct: float,
            soak_dheater_pct: int, heater_max_pct: float,
            heater_samples: int, heater_dry_learned: "float | None",
            heater_mai_learned: "float | None", heater_dev_learned: "float | None",
            heater_fc_learned: "float | None", heater_fc_samples: int,
            coherent_source: "_PlanSource | None" = None,
            cohort_dry_learned: "float | None" = None, cohort_samples: int = 0,
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
        # Dynamic Machine Controls (Heater) => % compensation.
        # Same coefficient as the drying-energy term in _green_moisture_effect, on
        # purpose: heater_dry_base drives the published RoR peak while this drives
        # the published setpoint; different water laws would print a peak the
        # plan's own burner value cannot produce.
        heater_compensation: float = (
            self._MOISTURE_DRY_HEATER_PCT_PER_POINT * moisture.value if moisture.known else 0.0)

        # Structure on the initial power: a dense bean takes the energy to the
        # core without marking, a soft one scorches at the same setting. Drying
        # and Maillard only — development is held by its own floor.
        structure_compensation: float = (
            _HEATER_DRY_PCT_PER_STRUCTURE_INDEX * structure.value if structure.known else 0.0)

        if is_light_roast and tech.light_heater_base_by_process is not None:
            # La correction technologie est déjà portée par heater_cmfc plus
            # haut : ce bloc reste petit pour ne pas la compter deux fois.
            HDB_WASHED, HDB_NATURAL, HDB_DECAF = tech.light_heater_base_by_process
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
        _grid_dry:float = (HEATER_C * 100.0) + heater_dry_process + heater_compensation + structure_compensation + cal_heater_dry_pct
        _grid_mai:float = (HEATER_M * 100.0) + heater_dry_process + heater_compensation + structure_compensation + cal_heater_mai_pct
        _grid_dev:float = (HEATER_FC * 100.0) + heater_dry_process + heater_compensation

        # ── Learned heater profile (design validé 2026-07-04, #5) ────────────
        # Burner % actually held by the coherent colour-matched reference roast
        # REPLACES the grid base (same progressive-adoption policy as FC/drop).
        # The learned value already embodies the operator's process/humidity/
        # altitude compensation on THIS machine — re-adding the grid corrections
        # would double-count, so at n≥3 the corrections are dropped (n=2 keeps
        # half via the blend). Heat-soak stays on top (batch-specific, absent
        # from the mostly-batch-1 history).
        heater_source: "_PlanSource" = _SOURCE_GRID
        _h_n = int(heater_samples or 0)
        _hl_dry = heater_dry_learned
        _hl_mai = heater_mai_learned
        _hl_dev = heater_dev_learned
        _notes: "list[str]" = []
        _heater_learned_n: int = 0
        if None not in (_hl_dry, _hl_mai, _hl_dev) and _h_n >= 2:
            heater_dry, heater_source = self._adopt_learned(_grid_dry, float(_hl_dry), _h_n)
            heater_maillard, _        = self._adopt_learned(_grid_mai, float(_hl_mai), _h_n)
            heater_dev, _             = self._adopt_learned(_grid_dev, float(_hl_dev), _h_n)
            if not heater_source.is_grid:
                if coherent_source:
                    heater_source = coherent_source
                ## Note émise APRÈS les clamps : elle annonce ce que le plan
                ## tient, pas ce que l'historique proposait.
                _heater_learned_n = _h_n
        else:
            heater_dry, heater_maillard, heater_dev = _grid_dry, _grid_mai, _grid_dev

        ## Lot 5 — le brûleur de CHARGE vient de la cohorte (même process, masse
        ## ± 50 g, toutes origines), pas de la famille : le grain ne dit pas
        ## comment la machine chauffe. Il passe APRÈS le profil de famille et le
        ## remplace sur cette seule phase ; le Maillard et le développement
        ## restent au grain, leur valeur suit la couleur visée.
        _cohort_n: int = int(cohort_samples or 0)
        _cohort_applied_n: int = 0
        if cohort_dry_learned is not None and _cohort_n >= 2:
            _dry_before = heater_dry
            heater_dry, _cohort_src = self._adopt_learned(
                _grid_dry, float(cohort_dry_learned), _cohort_n)
            if not _cohort_src.is_grid:
                ## Note émise APRÈS les clamps, comme celle du profil de famille :
                ## elle annonce ce que le plan TIENT, pas ce que la cohorte
                ## proposait — la correction inter-lot passe encore après.
                _cohort_applied_n = _cohort_n
                _logd.info(
                    f"RoastPlan: charge burner from cohort {heater_dry:.0f}% "
                    f"(was {_dry_before:.0f}%, n={_cohort_n})")

        # Heater ceiling: hardware limit, not a style choice — some elements
        # (e.g. the ITOP Cyberroaster's FIR/NIR emitter) degrade above a
        # machine-specific power fraction, so the upper clamp bound is read
        # from the roaster context instead of a fixed 100.0.
        _heater_max_pct: float = heater_max_pct

        # Heat-soak (batch-specific) applied on top of either base, then clamped
        # between the technology's support floor and the machine ceiling. Sous le
        # plancher la machine tient la température sans nourrir la réaction : un
        # réglage prescrit là est un RoR qui s'écroule, appris ou non.
        _floor_pct: float = min(tech.burner_floor_pct, _heater_max_pct)
        heater_dry      = _clamp(heater_dry + soak_dheater_pct, _floor_pct, _heater_max_pct)
        heater_maillard = _clamp(heater_maillard, _floor_pct, _heater_max_pct)
        heater_dev      = _clamp(heater_dev, _floor_pct, _heater_max_pct)

        if _cohort_applied_n:
            _notes.append(QApplication.translate(
                "tilauscope_roast_plan",
                "Charge burner from {0} roast(s) of the same process at this batch size, whatever the coffee: {1}% through drying.").format(
                _cohort_applied_n, f"{heater_dry:.0f}"))
        if _heater_learned_n:
            _notes.append(QApplication.translate(
                "tilauscope_roast_plan",
                "Heater profile learned from {0} matched roast(s): {1}/{2}/{3}% (dry/Maillard/dev)").format(
                _heater_learned_n, f"{heater_dry:.0f}", f"{heater_maillard:.0f}",
                f"{heater_dev:.0f}"))
            _logd.info(f"RoastPlan: heater from history {heater_dry:.0f}/{heater_maillard:.0f}/"
                       f"{heater_dev:.0f}% [{heater_source}] (n={_heater_learned_n})")

        # bean_energy remains import-compatible but is experimental
        # and non-constraining. No bean label or ambient value raises heater.
        _floor = FloorProfile(level_pct=0.0, release_fraction=0.0)
        _h_mai_free, _h_dev_free = heater_maillard, heater_dev

        heater_tp:float          = max(_floor_pct,
                                       heater_dry - (5.0 if not is_light_roast else 8.0))

        # ── Feu au FC appris — palier pre-FC de la rampe (item C, décision ──────
        # Tilau : FC appris de l'historique, backup = calcul actuel du plan,
        # c'est-à-dire la colonne dev comme avant). Cohorte couleur-assortie,
        # politique _adopt_learned habituelle, plausibilité [0,100].
        _hl_fc = heater_fc_learned
        _h_fc_n = int(heater_fc_samples or 0)
        if _hl_fc is not None and not (0.0 <= float(_hl_fc) <= 100.0):
            _hl_fc = None
        heater_pre_fc, heater_fc_source = self._adopt_learned(
            float(heater_dev), float(_hl_fc) if _hl_fc is not None else None, _h_fc_n)
        # Momentum through the crack, for a wet bean only. The seed still holds
        # ~4-5 % water at first crack and that steam under pressure is what
        # cracks it; a moist lot loses momentum right there. Arnephy is explicit
        # that energy can be pushed through the crack because steam's specific
        # heat is still high enough to absorb it.
        # Applied BEFORE the machine ceiling on purpose: on this roaster the
        # pre-FC setpoint is often already near heater_max_pct, and the hardware
        # limit must win over the correction, never the other way round.
        if moisture_fc_heater_pct:
            heater_pre_fc += moisture_fc_heater_pct
        heater_pre_fc = _clamp(heater_pre_fc, _floor_pct, _heater_max_pct)
        if not heater_fc_source.is_grid:
            if coherent_source:
                heater_fc_source = coherent_source
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
            tp_bt_c: float, dry_ror_average: float, to_native,
            heater_dry: float, heater_maillard: float, heater_dev: float,
            heater_pre_fc: float, dev_free_pct: float,
            floor: "FloorProfile | None", heater_max_pct: float,
            burner_floor_pct: float,
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
        _floor = floor
        _heater_max_pct: float = heater_max_pct
        _burner_floor: float = min(burner_floor_pct, _heater_max_pct)
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
        # pre-FC anchor (~1 min avant FC) — défini HORS du bloc heater car l'Air
        # Ramp l'utilise aussi ; sinon NameError quand un torréfacteur a l'airflow
        # mais pas le contrôle burner (_has_heater False).
        _pre_fc_c: float = max(_dry_c + 1.0, fc_bt - _bt_lead_c)

        # Pre-FC remains a learned/grid setpoint; it is not raised
        # by a bean-derived physical floor.
        # A non-neutral explicit FloorProfile is still honoured for compatibility
        # with experimental callers; plan generation always supplies neutral.
        if _floor is not None:
            heater_pre_fc = _clamp(max(heater_pre_fc, _floor.at(1.0)),
                                   _burner_floor, _heater_max_pct)
        # Le palier pre-FC ne peut jamais dépasser le palier mi-Maillard : le feu
        # ne remonte pas en Maillard (doctrine Tilau — un geste cumulé descend ou
        # tient, jamais l'inverse avant le FC). Sans ce plafond, un feu pre-FC
        # appris (heater_fc_learned, cohorte séparée du mi-Maillard) plus chaud
        # que le mi-Maillard fait basculer _build_heater_ramp_c dans son repli
        # non monotone, qui redessine fidèlement le creux-puis-remontée — un
        # geste que personne ne peut exécuter sur la machine.
        if heater_pre_fc > heater_maillard:
            _logd.info(f"RoastPlan: pre-FC heater {heater_pre_fc:.0f}% capped to "
                       f"the Maillard level {heater_maillard:.0f}% — fire never "
                       f"climbs back up before first crack")
            heater_pre_fc = heater_maillard

        # ── Cohérence du résumé de phase avec la Dev Ramp ──────────────────────
        # La Dev Ramp part du palier pre-FC et ne descend jamais de plus de
        # _DEV_BURNER_DROP_CAP (le feu se TIENT en développement). Sans ce
        # recalage, le résumé annonçait un feu dev que la rampe ne suit pas —
        # d'autant plus visible depuis que le plancher relève le palier pre-FC.
        heater_dev = _clamp(max(heater_dev, heater_pre_fc - _DEV_BURNER_DROP_CAP),
                            _burner_floor, _heater_max_pct)
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
        # (heater_dry), n=2 blend 50/50, n>=3 le profil cohérent tel quel. Donc sans
        # historique, aucun geste : le réglage de charge traverse le séchage.
        _hl_de = heater_de_learned
        _h_de_n = int(heater_de_samples or 0)
        if _hl_de is not None and not (0.0 <= float(_hl_de) <= 100.0):
            _hl_de = None
        heater_pre_de, heater_de_source = self._adopt_learned(
            float(heater_dry), float(_hl_de) if _hl_de is not None else None, _h_de_n)
        heater_pre_de = _clamp(heater_pre_de, _burner_floor, _heater_max_pct)
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

        # ── Rampe heater — ESCALIER PROGRESSIF DÈS LE TP (fondamental Tilau) ────
        # Les valeurs de jalon sont des CIBLES atteintes PROGRESSIVEMENT, À PARTIR
        # DU TP : jamais un saut brutal. Construit par _build_heater_ramp_c —
        # helper PARTAGÉ avec le replan pour que le plan vivant garde la forme
        # progressive (le replan TP écrasait l'escalier → « le feu ne bouge plus »).
        heater_ramp: list[dict] = (
            self._build_heater_ramp_c(
                tp_bt_c, _dry_c, fc_bt, _ror_maillard_c,
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
        # ── Drum Speed — UNE valeur de SETUP ────────────────────────────────
        # Doctrine Tilau : le tambour se choisit à la charge selon le poids
        # (dominant) et la densité, puis ne bouge plus — un geste in-roast
        # réorganise le lit de grains et aveugle le RoR mesuré 30-45 s.
        # La fraction de la plage RPM machine suit le ratio charge/charge-nominale
        # (400 g → 85 %, 250 g → 70 %) plus un petit terme densité ; chaque machine
        # applique sa propre plage min/max via rpm_to_percent.
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
            airflow_dependency_index: float, aw: "_GreenPairValue",
            tech: "_TechnologyProfile", inlet_air_mode: str,
            airflow_resolution_pct: float,
            dry_bt_temperature: float, fc_bt: float, pre_fc_c: float,
            drop_bt_temperature: float, to_native,
            heater_pre_fc: float, heater_dev: float,
            has_heater_control: bool, heater_resolution_pct: float,
            dev_trajectory_learned: "dict | None", dev_traj_samples: int,
            airflow_dry_learned: "float | None" = None,
            airflow_mai_learned: "float | None" = None,
            airflow_dev_learned: "float | None" = None,
            airflow_samples: int = 0,
            coherent_source: "_PlanSource | None" = None,
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
        # instead of a binary technology toggle.
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

        airflow_base = ([round(v) for v in tech.airflow_pct]
                        if tech.airflow_pct is not None else
                        [round(_interp_base(28, 15)),
                         round(_interp_base(42, 22)),
                         round(_interp_base(60, 32))])
        extraction_base = [
            round(_interp_base(35, 22)),
            round(_interp_base(52, 32)),
            round(_interp_base(70, 42)),
        ]

        # Airflow clears the steam, so it follows the aw — the free fraction is
        # what evaporates. One-sided upward, the baseline being set by smoke.
        #
        # What was here: `3.0 if humidity > 11.0 or humidity < 9.0`. Two defects.
        # It opened the air by the same 3 % for a WET bean and for a DRY one —
        # opposite physics, identical response. And 0.0 is the "not measured"
        # sentinel, so `0.0 < 9.0` was true: a bean with no moisture reading was
        # treated as very dry and had its airflow opened on no evidence at all.
        #
        # The extraction compensation that lived here (moisture, and +3 % for
        # ambient humidity over 70 %) is gone: it never reached an output on any
        # machine — the AirWave programme overwrites the extraction list when the
        # device is present, and empties it when it is absent.
        airflow_compensation_percentage: float = (
            _AIRFLOW_PCT_PER_AW_INDEX * max(0.0, aw.value) if aw.known else 0.0)
        extraction_compensation_percentage: float = 0.0

        AIRFLOW_MIN = 20.0
        ## Pas de plancher d'air au séchage : 20 % n'est pas une limite machine,
        ## et il plaquait toute la colonne à 20 sur une machine pull.
        AIRFLOW_MIN_DRY = 0.0
        EXTRACTION_MIN = 30.0
        _airflow_step: float = airflow_resolution_pct # use roaster adjustement steps else set to 5% per default
        airflow_targets = [
            airflow_base[0] + airflow_compensation_percentage,
            airflow_base[1] + airflow_compensation_percentage,
            airflow_base[2] + airflow_compensation_percentage,
        ]
        # Pull machines (rear suction near the exhaust) strip heat as airflow rises;
        # bias the heat-critical DRY phase lower, scaled by airflow dependency.
        # Sauté quand la technologie pose ses propres valeurs : ce qui refroidit
        # le tambour est l'EXTRACTION, pas le ventilateur d'admission.
        if inlet_air_mode == "pull" and tech.airflow_pct is None:
            airflow_targets[0] -= round(_adi * 6.0)
        _airflow_n = int(airflow_samples or 0)
        for index, learned in enumerate((airflow_dry_learned, airflow_mai_learned,
                                         airflow_dev_learned)):
            if learned is not None and _airflow_n >= 2:
                airflow_targets[index], _ = self._adopt_learned(
                    airflow_targets[index], float(learned), _airflow_n)
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
            air = finalize_value(airflow_targets[i], AIRFLOW_MIN_DRY if i == 0 else AIRFLOW_MIN)
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

        # ── Trajectoire apprise partagée + helper (Air Ramp & Dev Ramp) ────────
        _dev_traj = dev_trajectory_learned or {}
        _dev_traj_n = int(dev_traj_samples or 0)
        _dev_use_learned = _dev_traj_n >= 2
        _DEV_EXT_RISE_CAP = 10.0   # AirWave puissant : montée douce (≤ +10 vs Maillard)
        def _mai_pct(lst: "list", i: int) -> "float | None":
            try: return float(str(lst[i]).rstrip('%'))
            except (IndexError, ValueError, TypeError): return None

        # ── Rampe AIRFLOW de MAILLARD — montée PROGRESSIVE dès mi-Maillard ──────
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

        # ── Franchissement du DRY END — escalier, pas un à-coup ────────────────
        # L'air de séchage était TENU puis posé d'un bloc sur la valeur Maillard
        # au jalon : un saut de plus d'un cran, que personne n'exécute d'un geste.
        # Il monte maintenant par cran machine dans l'approche du DRY END, pour y
        # arriver déjà à la bonne valeur — même géométrie que le feu, qui atteint
        # son palier avant le jalon plutôt qu'au jalon.
        _air_dry = _mai_pct(airflow, 0)
        if (_air_dry is not None and _air_mai is not None
                and _air_mai > _air_dry + _airflow_step * 1.5):
            _d0 = round(_air_dry / _airflow_step) * _airflow_step
            _de_levels = int(round((_air_mai - _d0) / _airflow_step))
            for _k in range(1, _de_levels + 1):
                _ade = (_de_levels - _k + 1) * _AIR_DE_STEP_LEAD_C
                air_ramp.append({
                    "bt": round(to_native(dry_bt_temperature - _ade), 1),
                    "_ade": round(_ade, 2),
                    "airflow": int(_clamp(_d0 + _airflow_step * _k, AIRFLOW_MIN, 100.0))})

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
                # _af = fraction mi-Maillard→pre-FC de CE palier, conservée pour
                # que le replan re-cale les seuils à LEUR place réelle (comme le
                # Dev Ramp avec _f), pas en répartition uniforme.
                air_ramp.append({"bt": round(to_native(_bt_a), 1),
                                 "_af": round(_frac, 4),
                                 "airflow": int(_clamp(_v, AIRFLOW_MIN, 100.0))})

        # ── Rampe de DÉVELOPPEMENT (Dev Ramp) — ESCALIER FIN, feu ↓ / air ↑ ─────
        # Prolonge les rampes Maillard EN CONTINUITÉ : heater part de sa valeur
        # PRE-FC (heater_dev, sinon remontée brutale au FC), airflow part de sa
        # valeur AU FC (_air_fc, la Maillard Air Ramp s'y arrête) et monte plus
        # intensément vers la cible dev. Pas d'UNE résolution, seuils rapprochés,
        # cible apprise (f=0.75) si historique ≥ 2 sinon colonne DEV.
        # item C : le dev part de la valeur pre-FC RÉELLE de la rampe
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
        # ── TENIR LE FEU en dev (spec AutoPilot §3sexies, banc 2026-07-11) ──────
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
        # ── Airflow SOUTIENT la réaction pendant que le FEU DESCEND en dev ──────
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
        _dev_ramp_source = (
            (coherent_source or _PlanSource(_SRC_LEARNED, _dev_traj_n,
                                            f"learned (n={_dev_traj_n})"))
            if _dev_use_learned
            # "default" rather than "grid": the development ramp has no grid
            # row of its own, it falls back to the phase columns.
            else _PlanSource(_SRC_GRID, 0, "default"))

        # ── La colonne DEV d'airflow dit ce que la Dev Ramp fait ───────────────
        # Symétrique du brûleur (_DEV_BURNER_DROP_CAP plus haut). La colonne
        # sortait de la grille de base : ni la cible APPRISE (f=0.75), ni le
        # plancher de soutien qui ouvre l'air à mesure que le feu descend, ne la
        # touchaient. Elle annonçait donc « Air 40 % » pendant que le plan monte
        # à 50 % — et cette colonne n'est pas décorative : l'AutoPilot en fait sa
        # cible DEV et la recommandation lue par l'opérateur sur machine
        # read-only en sort mot pour mot.
        # Reprise de la DERNIÈRE valeur RÉELLEMENT posée par la rampe plutôt que
        # de `_dev_end[0]` : la rampe quantifie au pas machine, et recopier la
        # formule laisserait les deux diverger d'un pas au prochain changement de
        # résolution. Ici l'accord est structurel.
        if 0 in _dev_end and len(airflow) > 2:
            _air_posted = [e["airflow"] for e in _dev_ramp if "airflow" in e]
            if _air_posted:
                airflow[2] = f"{_air_posted[-1]:.0f}%"

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
            # --- 1. Where the curve is DRAWN through the turning point ---
            # ⚠️ Pas une prévision : voir _tp_placeholder_c, qui porte la loi
            # masse→creux (et ses bornes) pour tout le module.
            # °C-PURE: this function works entirely in °C. generate_roast_plan
            # converts the returned grids/waypoints to °F at its output boundary.
            tp_temperature = self._tp_placeholder_c(
                charge_temperature, charge_weight, self._nominal_weight_g())
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

    @staticmethod
    def _read_roast_destination() -> str:
        """Destination courante du café, normalisée sur la table des bonus."""
        _dest = str(QSettings().value('tilauscope/roast_destination',
                                      _DEV_DESTINATION_DEFAULT, str) or "").strip().lower()
        return _dest if _dest in _DEV_DESTINATION_BONUS_SEC else _DEV_DESTINATION_DEFAULT

    def generate_roast_plan(self, bean:GreenBean, agtron_target:AgtronScale, ambient_temp:float, ambient_humidity:float, charge_weight:float, roast_altitude:float, bt_deviation:ProbeDeviation|None, airwave_present:bool=False, minutes_since_last_drop:'float | None'=None):

        # ── UNIT NORMALISATION ───────────────────────────────────────────────────
        # All internal physics maths are in °C.
        # If Artisan is running in °F the caller passes °F values; convert them
        # to °C here so every formula below is unit-safe.
        # We convert back to the native unit only in the final output dict.
        from artisanlib.util import fromFtoCstrict, fromCtoFstrict

        # La destination peut avoir changé depuis la construction du moteur
        # (celui-ci est mis en cache par ses appelants) : on la relit ici.
        self.roast_destination = self._read_roast_destination()

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
        # `None` is the "not measured" sentinel INSIDE the model (spec §7), so a
        # room genuinely at 0 °C stays a measurement. The UI spin boxes still send
        # 0.0 for "empty" and cannot express None, so the wire sentinel is
        # normalised once, here, rather than being re-interpreted at each use.
        # Making a real 0 °C readable end to end means teaching the callers to
        # send None — a UI change, not a physics one.
        _ambient_measured_c: "float | None" = (
            ambient_temp_c if float(ambient_temp or 0.0) != 0.0 else None)
        # (charge_weight, roast_altitude are unit-independent; ambient humidity no
        #  longer takes part in the roast at all — see the pair doctrine)
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

        # ── Green-coffee variables, resolved ONCE ──────────────────────────────
        # Every downstream consumer reads these, never the raw fields. Moisture
        # and aw are independent (energy vs evaporation); structure is still a
        # pair, so a bean cannot be counted twice through density AND altitude.
        # See the doctrine at the top of the module and spec §2.2.
        _moisture: _GreenPairValue = _resolve_green_moisture(humidity)
        _aw: _GreenPairValue = _resolve_green_aw(bean.water_activity)
        _structure: _GreenPairValue = _resolve_green_structure(density, culture_altitude)
        _logd.info(
            f"RoastPlan: moisture {_moisture.value:+.2f} pt [{_moisture.label or 'absent'}], "
            f"aw {_aw.value:+.2f} idx [{_aw.label or 'absent'}], "
            f"structure {_structure.value:+.2f} [{_structure.label or 'absent'}]")

        # ── Roaster context shortcuts ──────────────────────────────────────────
        # All machine-specific constants come from RoasterContext when available.
        ctx = self._roaster_ctx  # may be None → use generic defaults below

        # Tout ce que le plan fait différemment SELON LA FAÇON DE CHAUFFER passe
        # par ce profil — plus de drapeau testé en six endroits.
        _tech: _TechnologyProfile = _technology_profile(
            ctx.is_radiant_electric if ctx is not None else False)

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

        # Deep-copy the shared base table (tilauscope_types.ROASTING_BASIC_BASE):
        # the FIR/NIR correction below mutates entries in place, and the same
        # constant is read as-is by the BeanCave coach.
        roasting_basic_base: RoasterBasicPlan = copy.deepcopy(ROASTING_BASIC_BASE)
        target_roast_category = agtron_target.name
        is_light_roast = target_roast_category in ["Light", "Very Light"]
        # La technologie de chauffe réécrit la ligne de sa catégorie : charge
        # exclue, la bande de charge process/BT en reste propriétaire.
        _override = _tech.plan_overrides.get(target_roast_category)
        if _override:
            _row = next((p for p in roasting_basic_base.plans
                         if p.name == target_roast_category), None)
            if _row is not None:
                for _key, _value in _override.items():
                    setattr(_row, _key, _value)
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

        # Learned FC (per bean × machine) from the coherent historical roast.
        # Adoption policy (progressive): n>=3 → medoid value adopted as-is;
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
        # The history dict crosses a JSON boundary (it is frozen into the golden
        # snapshot), so it carries the key and the label as two plain strings
        # and the source object is rebuilt here.
        _coherent_n = int(history.get("coherent_profile_samples", 0) or 0) if history else 0
        _coherent_source: "_PlanSource | None" = None
        if history and history.get("coherent_profile_source"):
            _coherent_source = _PlanSource(
                str(history.get("coherent_profile_key") or _SRC_GRID), _coherent_n,
                str(history["coherent_profile_source"]))
        if not fc_source.is_grid and _coherent_source and _coherent_n >= 2:
            fc_source = _coherent_source

        # ── Charge setup: band by PROCESS, bean/ambient modulation, and
        # inter-batch heat soak — extracted to _charge_setup (banc 2026-08-05),
        # see that method for the doctrine comments. Called here, ahead of the
        # FC regression below, so its pre-modulation band midpoint
        # (nominal_temperature_c) is available for that adjustment, exactly as
        # in the original interleaved order — the regression does not depend
        # on the modulation/soak outcome, and the modulation/soak does not
        # depend on fc_bt, so pulling the whole stage ahead of the regression
        # does not change the result.
        ## Poids du terme de famille = confiance dans l'identité génétique.
        ## Hoos la pose lui-même : 20-25 % de pollinisation croisée, erreurs de
        ## pépinière, identifications à l'œil. Un mélange dilue la génétique du
        ## composant nommé, d'où la demi-confiance ; une variété absente ou non
        ## reconnue annule le terme et ramène au comportement antérieur.
        _family_weight: float = 0.0
        if getattr(bean, "varieties", ""):
            _family_weight = 0.5 if getattr(bean, "is_blend", False) else 1.0
        _charge = self._charge_setup(
            process_type_lower=process_type_lower,
            varieties=getattr(bean, "varieties", "") or "",
            family_weight=_family_weight,
            moisture=_moisture, structure=_structure,
            ambient_temp_c=_ambient_measured_c, minutes_since_last_drop=minutes_since_last_drop,
            thermal_mass_idx=_thermal_mass_idx, heat_retention_idx=_heat_retention_idx)
        _charge_temperature = _charge.nominal_temperature_c

        # FC regression adjustment by charge temperature
        # If learned FC has regression coefficients, adjust it based on planned charge.
        _fc_regression_slope = history.get("fc_regression_slope") if history else None
        _fc_regression_offset = history.get("fc_regression_offset") if history else None
        _fc_regression_meta = history.get("fc_regression", {}) if history else {}
        _charge_in_regression_range = (
            _fc_regression_meta.get("charge_min_c") is not None
            and float(_fc_regression_meta["charge_min_c"]) - 2.0 <= _charge_temperature
            <= float(_fc_regression_meta["charge_max_c"]) + 2.0)
        # Gated on the KEY, not on the label. This line read
        # `fc_source == "learned"` while the label has always been
        # "learned (n=3)" (and "medoid (n=3)" once the coherent profile takes
        # over), so the condition was never true and the whole validated
        # regression above it was dead. Only a fully learned first crack earns
        # the adjustment: at n=2 the value is already half grid, and shifting a
        # blend by a slope fitted on the same roasts would count them twice.
        if (fc_source.key == _SRC_LEARNED and _fc_regression_slope is not None
                and _fc_regression_offset is not None and _charge_in_regression_range):
            fc_bt_adjusted = round(_fc_regression_slope * _charge_temperature + _fc_regression_offset, 1)
            if 175.0 <= fc_bt_adjusted <= 212.0:
                _logd.info(f"RoastPlan: FC regression adjustment: charge {_charge_temperature:.1f}°C "
                           f"→ FC {fc_bt:.1f}°C → {fc_bt_adjusted}°C (slope={_fc_regression_slope:.4f})")
                fc_bt = fc_bt_adjusted
        elif not fc_source.is_grid:
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

        # DTR is not a target here: development duration is set below from the
        # professional absolute-time band, and the ratio is only ever reported as
        # a consequence — see dtr_achieved further down. roast_constraints.dtr_pct
        # is kept as a reference window for that sanity check only, never a driver.

        # ── Phase timings anchored on TOTAL ──────────────────────────────────
        # Base durations extracted to _base_phase_durations — see that method
        # for the doctrine comments on the split.
        total_time_min, dry_time_min, dev_time_min = self._base_phase_durations(
            roast_constraints=roast_constraints, structure=_structure)
        ## Destination : le seul endroit où elle agit. `dev_time_min` est un
        ## INTRANT de l'enveloppe (arbitrage 2026-08-04 : le développement garde
        ## sa durée, c'est son ΔT qui se déduit), donc le décalage se propage
        ## seul jusqu'à la température de largage et à la cible de perte de masse.
        _dest_bonus_min: float = (_DEV_DESTINATION_BONUS_SEC[self.roast_destination] / 60.0)
        if _dest_bonus_min > 0.0:
            dev_time_min += _dest_bonus_min
            total_time_min += _dest_bonus_min
            _logd.info(f"RoastPlan: destination {self.roast_destination} "
                       f"+{_dest_bonus_min * 60.0:.0f}s of development")
        _grid_dry_time_min: float = dry_time_min

        heater_dry_base:float = roast_constraints.heater_cmfc[0]*100

        # ── Bean water: drying energy, first-crack momentum, Maillard body ──
        # The charge is not modulated here: it is driven from inside the charge
        # modulation, where bean properties belong.
        effect = self._green_moisture_effect(_moisture)
        dry_time_min += effect.d_dry_time_min
        heater_dry_base += effect.d_heater_dry_pct
        # d_airflow_pct is consumed by _resolve_airflow_extraction, which reads the
        # resolved water pair directly — see the call further down.

        # ── Ambient temperature: the beans start at ROOM temperature ────────
        # Applied here (not only as a charge nudge): 400 g × 1.7 J/g·K × 10 K
        # = 6.8 kJ ≈ 19 s of drying at the ~350 W this machine delivers to the
        # charge — a winter and a summer roast of the same coffee differ.
        if _ambient_measured_c is not None:
            _ambient_dry_min: float = (
                _AMBIENT_DRY_MIN_PER_10K * (20.0 - _ambient_measured_c) / 10.0
                * (charge_weight / 400.0))
            dry_time_min += _ambient_dry_min
            _logd.debug(
                f"Ambient {_ambient_measured_c:.1f}°C on {charge_weight:.0f} g → "
                f"drying {_ambient_dry_min:+.2f} min")

        ## Notes qui appartiennent au PLAN, pas à l'historique : elles doivent
        ## sortir même sur un plan de grille pure, où `history` est None.
        _plan_notes: "list[str]" = []

        # ── Lot 4 : l'enveloppe de RoR contraint, les durées suivent ────────
        # Le TP est calculé ici (et non plus plus bas) parce que la durée de
        # séchage part de lui. Temps du TP : constante machine quand la
        # technologie en pose une, sinon la loi de masse historique.
        _tp_time_min: float = (_tech.tp_time_min if _tech.tp_time_min is not None
                               else max(0.75, min(1.5, 0.9 + charge_weight / 1500.0)))
        # ⚠️ Placeholder de tracé, pas une prévision (voir _tp_placeholder_c).
        # Même appel que la courbe, masse comprise : sans le terme de masse, le
        # séchage d'un petit lot partait 25 °C trop bas et gonflait le RoR
        # calculé — erreur qu'un écrêtage dans la bande idéale masquait ensuite
        # au lieu de la corriger.
        _tp_bt_c: float = self._tp_placeholder_c(
            charge_bt_temperature, charge_weight, _nominal_weight_g)

        _env_timing: "_EnvelopeTiming | None" = None
        _env_dev_delta_c: float = 0.0
        if _tech.ror_envelope is not None:
            ## Cible de RoR au drop de la technologie, interpolée sur le niveau —
            ## c'est vers elle que la pente descend pendant le développement.
            _env_drop_ror: float = (_tech.ror_at_drop_dark
                                    + (_tech.ror_at_drop_light - _tech.ror_at_drop_dark)
                                    * agtron_ratio)
            _env_timing = self._envelope_timing(
                envelope=_tech.ror_envelope, tp_time_min=_tp_time_min,
                tp_bt_c=_tp_bt_c, dry_bt_c=dry_bt_temperature, fc_bt_c=fc_bt,
                dev_time_min=dev_time_min, drop_ror_c=_env_drop_ror,
                # Les corrections eau/ambiante restent : elles sont physiques et
                # s'ajoutent à la durée déduite, elles ne la remplacent pas.
                dry_correction_min=dry_time_min - _grid_dry_time_min,
                dry_floor_min=self._dry_floor_min(
                    charge_weight, _nominal_weight_g, _dev_inertia))
            _env_dev_delta_c = _env_timing.dev_delta_c
            if _env_timing.dry_bt_shift_c > 0.0:
                ## Sécher plus longtemps à la même pente, c'est arriver plus haut :
                ## le DRY END suit la durée, et le span Maillard s'en déduit.
                dry_bt_temperature += _env_timing.dry_bt_shift_c
                ma_bt_temperature = fc_bt - dry_bt_temperature
                _logd.info(
                    f"RoastPlan: dry end raised {_env_timing.dry_bt_shift_c:.1f}°C to "
                    f"{dry_bt_temperature:.1f}°C — a floored drying arrives higher, "
                    f"and the rate of rise has to keep falling into Maillard")
            dry_time_min = _env_timing.dry_time_min
            total_time_min = dry_time_min + _env_timing.maillard_time_min + dev_time_min
            _logd.info(
                f"RoastPlan: envelope timing dry={dry_time_min:.2f}min "
                f"maillard={_env_timing.maillard_time_min:.2f}min "
                f"(RoR {_env_timing.dry_ror_c:.1f} → {_env_timing.maillard_ror_c:.1f} °C/min)")
            if _env_timing.maillard_compressed:
                ## Le mouvement de RoR exigé est LUI-MÊME la preuve : à cette
                ## masse le séchage est court, le Maillard doit donc être mené
                ## plus vif que l'enveloppe nominale pour ne pas le dépasser.
                _logd.info(
                    f"RoastPlan: maillard compressed to {_env_timing.maillard_time_min:.2f}min "
                    f"({_env_timing.maillard_ror_c:.1f}°C/min) — drying runs "
                    f"{_env_timing.dry_ror_c:.1f}°C/min at this batch size")
                _plan_notes.append(QApplication.translate(
                    "tilauscope_roast_plan",
                    "Small batch: drying is short here, so Maillard is led at {0}°/min rather than the usual easing. Any slower and it would outlast drying, which this machine does not do.").format(
                    f"{_env_timing.maillard_ror_c * (1.8 if _is_fahrenheit else 1.0):.0f}"))
            if _env_timing.drying_stretched:
                ## Le mouvement de RoR exigé est LUI-MÊME la preuve : sécher
                ## plus vite que le Maillard demanderait de tenir la pente haute
                ## puis de la casser. On rallonge le séchage et on le dit.
                _logd.warning(
                    f"RoastPlan: drying stretched to {dry_time_min:.2f}min — a "
                    f"shorter one would put Maillard above it; drying now runs at "
                    f"{_env_timing.dry_ror_c:.1f}°C/min against "
                    f"{_env_timing.maillard_ror_c:.1f} in Maillard")
                _plan_notes.append(QApplication.translate(
                    "tilauscope_roast_plan",
                    "Drying is planned at {0}°/min rather than faster: any shorter and Maillard would outlast it, which this machine does not do. From the dry end the curve keeps easing, to {1}°/min across Maillard.").format(
                    f"{_env_timing.dry_ror_c * (1.8 if _is_fahrenheit else 1.0):.0f}",
                    f"{_env_timing.maillard_ror_c * (1.8 if _is_fahrenheit else 1.0):.0f}"))
        elif dry_time_min < float(roast_constraints.drying_time[0]):
            # Floored on the BOTTOM of the style window, not on its middle:
            # flooring on the nominal duration would cancel the very shortening
            # a dry bean or a warm room earns. They may dry as fast as the style
            # allows, never faster.
            dry_time_min = float(roast_constraints.drying_time[0])

        # Fenêtres d'adoption de l'historique : autour de la valeur déduite de
        # l'enveloppe quand elle gouverne, autour de la grille de style sinon.
        # L'historique personnalise, il ne ramène pas la grille par la fenêtre.
        _ENV_WINDOW: float = 0.75
        _drying_band: "tuple[float, float]" = roast_constraints.drying_time
        _maillard_band: "tuple[float, float]" = roast_constraints.maillard_time
        if _env_timing is not None:
            _drying_band = (dry_time_min - _ENV_WINDOW, dry_time_min + _ENV_WINDOW)
            _maillard_band = (_env_timing.maillard_time_min - _ENV_WINDOW,
                              _env_timing.maillard_time_min + _ENV_WINDOW)

        # ── Cross-roast timing calibration + physical duration floors ───────
        # Extracted to _calibrate_and_floor_phase_durations (banc 2026-08-05) —
        # see that method for the calibration and floor doctrine comments, and
        # for why the floors must run after the calibration.
        _timing = self._calibrate_and_floor_phase_durations(
            dry_time_min=dry_time_min, total_time_min=total_time_min, dev_time_min=dev_time_min,
            drying_time_band=_drying_band,
            maillard_time_band=_maillard_band,
            t_dry_raw=history.get("timing_dry_min_learned") if history else None,
            t_fc_raw=history.get("timing_fc_min_learned") if history else None,
            t_n=int(history.get("timing_samples", 0) or 0) if history else 0,
            coherent_source=(_coherent_source if _coherent_n >= 2 else None),
            charge_weight_g=charge_weight, batch_optimal_g=_nominal_weight_g,
            thermal_inertia=_dev_inertia)
        dry_time_min      = _timing.dry_time_min
        maillard_time_min = _timing.maillard_time_min
        timing_source      = _timing.timing_source
        _cal_heater_dry    = _timing.cal_heater_dry_pct
        _cal_heater_mai    = _timing.cal_heater_mai_pct
        if _timing.notes and history is not None:
            history["actions"] = (history.get("actions") or []) + _timing.notes

        # ── Maillard body compensation for an over-dried bean ───────────────
        # Applied AFTER the calibration and its floors, because it is not a
        # duration correction — it is a FLAVOUR one, and it must not be eaten by
        # a floor that was computed for other reasons.
        # Less water means less steam, so the internal pressure that expands the
        # cell walls never builds; Hoos calls the result a flat, thin cup, and it
        # happens whatever the development is. His body lever is MAI duration —
        # longer Maillard makes the melanoidins that carry viscosity — so a dry
        # bean buys back with time what it cannot build with pressure.
        # One-sided: a wet bean already has the pressure and needs no help here.
        if effect.d_maillard_time_min:
            maillard_time_min += effect.d_maillard_time_min
            _logd.info(
                f"RoastPlan: Maillard {effect.d_maillard_time_min:+.2f} min — dry green "
                f"[{_moisture.label}] builds less internal pressure, body compensated by time")

        # determine DRY RoR peak (°C/min — scaled at the output boundary)
        ## Sous enveloppe, le pic post-TP est la première ancre — plus la loi
        ## « % brûleur ÷ 75 × 12 », qui sortait un pic SOUS la moyenne du
        ## séchage, ce qu'aucune courbe ne peut faire.
        dry_ror_peak:float = (_tech.ror_envelope[0] if _tech.ror_envelope is not None
                              else (heater_dry_base / 75.0 * _tech.dry_ror_peak_c
                                    if _tech.dry_ror_peak_follows_heater
                                    else _tech.dry_ror_peak_c))
        # Real post-TP dry-phase RoR: rise from the turning point to dry-end over
        # the active drying time. The old (charge - dry_end)/dry_time ignored the
        # post-charge dip and was not the drying RoR at all. Uses the machine TP
        # (placeholder de tracé) and the planned TP time (same model as the curve).
        # _tp_time_min et _tp_bt_c sont posés plus haut, avec l'enveloppe.

        # Typical post-TP reference only. The placeholder TP cannot
        # support an attainability calculation; live replanning uses the real TP.
        _peak_ror_reference_c = (ctx.peak_ror_reference_c if ctx is not None else 21.0)
        _peak_ror_note = ""  # temporary output compatibility; no ceiling warning

        _dry_active_min: float = max(0.5, dry_time_min - _tp_time_min)
        dry_ror_average: float = (dry_bt_temperature - _tp_bt_c) / _dry_active_min
        if _env_timing is None:
            # Align the dry RoR target to the CHARGE->DRY band so the plan target stays
            # consistent with the live phase classifier (no "on plan" reading as warn).
            # Band requested in °C — the internal frame; scaled at the output boundary.
            _dry_band_lo, _dry_band_hi = get_ror_ideal_band("drying", "C")
            dry_ror_average = max(_dry_band_lo, min(_dry_band_hi, dry_ror_average))
        # Sous enveloppe, le RoR imprimé reste celui qu'IMPLIQUE la durée
        # retenue : si un plancher ou l'historique a déplacé la durée, c'est la
        # durée qui gagne et le plan le dit — il n'écrête pas le chiffre pour
        # sauver les apparences.
        elif abs(dry_ror_average - _env_timing.dry_ror_c) > 2.0:
            _logd.warning(
                f"RoastPlan: retained drying {dry_time_min:.2f}min implies "
                f"{dry_ror_average:.1f}°C/min, envelope asks "
                f"{_env_timing.dry_ror_c:.1f} — the duration was moved after the envelope")

        # maillard_time_min set in the timing-calibration block above
        # (total - dry - dev by deduction, or learned from history when the
        # cohort allows it).
        # GEOMETRY-DERIVED maillard RoR: the real average slope the BT curve will
        # follow between the dry-end and FC anchors (internal °C; scaled at the
        # output boundary).
        ror_maillard:float = (ma_bt_temperature / maillard_time_min
                              if maillard_time_min > 0 else ror_maillard_expected)

        # dev_time_min set from the professional development-time band above
        # (absolute duration, not DTR-derived).

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
        # by the grid clamp below. Keep this bounded grid geometry independent
        # from measured colour; no universal DROP/Agtron response is assumed.
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
            coherent_source=(_coherent_source if _coherent_n >= 2 else None),
            drop_ror_learned_c=(history.get("drop_ror_learned_c") if history else None),
            drop_ror_samples=(int(history.get("drop_ror_samples", 0) or 0) if history else 0),
            fc_bt=fc_bt, dev_time_min=dev_time_min,
            dev_ror_expected=dev_ror_expected, agtron_ratio=agtron_ratio,
            charge_weight=charge_weight, density=density, moisture_pct=humidity or 0.0,
            nominal_weight_g=_nominal_weight_g, heat_retention=_heat_retention_idx,
            tech=_tech,
            env_dev_delta_c=(_env_dev_delta_c if _env_timing is not None else None),
            env_fc_entry_ror_c=(_env_timing.fc_entry_ror_c if _env_timing is not None else None))
        drop_bt_temperature = _drop.drop_bt_temperature
        drop_source = _drop.drop_source
        dev_ror = _drop.dev_ror
        drop_ror = _drop.drop_ror
        drop_ror_source = _drop.drop_ror_source
        if _drop.notes:
            _plan_notes += _drop.notes

        # Le TP annoncé est celui que la courbe DESSINE — un seul modèle.
        # Il y avait ici un second calcul indépendant, `charge − 30 × (1,5 −
        # inertie) − masse/50`, qui publiait « Estimated TP » : mesuré sur les
        # 94 roasts du corpus le 2026-08-11, il se trompait de **+43 °C en
        # moyenne** (annonçait ~147 °C là où la machine descend à 96) et
        # contredisait de ~50 °C la courbe imprimée juste à côté.
        tp_temperature: float = _tp_bt_c

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
        ## Cohorte : même process, même gabarit de lot, toutes origines (lot 5).
        _cohort_dry, _cohort_n = self._cohort_charge_burner(
            process_type=process_type, charge_weight_g=charge_weight)
        _burner = self._resolve_burner_setpoints(
            moisture=_moisture, structure=_structure,
            moisture_fc_heater_pct=effect.d_heater_fc_pct,
            is_light_roast=is_light_roast, tech=_tech,
            agtron_mean=agtron_mean, process_type_lower=process_type_lower,
            process_type=process_type,
            bean_varieties=bean.varieties or "", bean_country=bean.country or "",
            ambient_temp_c=_ambient_measured_c,
            roast_constraints=roast_constraints,
            cal_heater_dry_pct=_cal_heater_dry, cal_heater_mai_pct=_cal_heater_mai,
            soak_dheater_pct=_soak_dheater, heater_max_pct=_heater_max_pct,
            heater_samples=(int(history.get("heater_samples", 0) or 0) if history else 0),
            heater_dry_learned=(history.get("heater_dry_learned") if history else None),
            heater_mai_learned=(history.get("heater_mai_learned") if history else None),
            heater_dev_learned=(history.get("heater_dev_learned") if history else None),
            heater_fc_learned=(history.get("heater_fc_learned") if history else None),
            heater_fc_samples=(int(history.get("heater_fc_samples", 0) or 0) if history else 0),
            coherent_source=(_coherent_source if _coherent_n >= 2 else None),
            cohort_dry_learned=_cohort_dry, cohort_samples=_cohort_n)
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
        if _burner.notes:
            _plan_notes += _burner.notes

        ## Garde-fou du temps de TP : la constante machine vaut à 70-80 % de
        ## brûleur de charge (vérifiée sur 91 roasts, tous dans cette fenêtre).
        ## Sous ce feu la machine repart moins vite, le TP recule, et toutes les
        ## durées qui en découlent avec lui. On le dit — on ne l'extrapole pas.
        if (_tech.tp_time_min is not None
                and heater_dry < _tech.tp_time_heater_pct - 0.5):
            _logd.warning(
                f"RoastPlan: drying burner {heater_dry:.0f}% is below the "
                f"{_tech.tp_time_heater_pct:.0f}% the {_tp_time_min:.2f}min turning "
                f"point was verified at — the real TP will come later")
            _plan_notes.append(QApplication.translate(
                "tilauscope_roast_plan",
                "The plan holds {0}% through drying, under the {1}% its turning-point timing was measured at: expect the turning point, and everything after it, a little later than printed.").format(
                f"{heater_dry:.0f}", f"{_tech.tp_time_heater_pct:.0f}"))

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
            tp_bt_c=_tp_bt_c, dry_ror_average=dry_ror_average,
            to_native=_to_native,
            heater_dry=heater_dry, heater_maillard=heater_maillard, heater_dev=heater_dev,
            heater_pre_fc=heater_pre_fc, dev_free_pct=_h_dev_free,
            floor=None, heater_max_pct=_heater_max_pct,
            burner_floor_pct=_tech.burner_floor_pct,
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
        # Informational machine guidance only; development is excluded.
        _heater_authority = _heater_authority_notes(
            [heater_dry, heater_maillard, heater_pre_fc]
            + [float(step["heater"]) for step in heater_ramp if step.get("heater") is not None],
            (ctx.heater_support_threshold_pct if ctx is not None else None),
            (ctx.heater_caution_pct if ctx is not None else None),
            (ctx.display_name if ctx is not None else ""))

        # ── Airflow, extraction and their two ramps — extracted to
        # _resolve_airflow_extraction (banc 2026-08-05), see that method for
        # the doctrine comments (airflow-dependency-scaled base, the
        # Maillard Air Ramp opening ~40% of the total rise, and the
        # Development Ramp's burner-hold/air-support coupling).
        _airflow_ext = self._resolve_airflow_extraction(
            airwave_present=self._airwave_present,
            airflow_dependency_index=_airflow_dep_idx, aw=_aw, tech=_tech,
            inlet_air_mode=(getattr(ctx, "inlet_air_mode", "push") if ctx is not None else "push"),
            airflow_resolution_pct=(ctx.airflow_resolution_pct if ctx else 5.0),
            dry_bt_temperature=dry_bt_temperature, fc_bt=fc_bt, pre_fc_c=_pre_fc_c,
            drop_bt_temperature=drop_bt_temperature, to_native=_to_native,
            heater_pre_fc=heater_pre_fc, heater_dev=heater_dev,
            has_heater_control=_has_heater, heater_resolution_pct=_heater_res,
            dev_trajectory_learned=(history.get("dev_trajectory_learned") if history else None),
            dev_traj_samples=(int(history.get("dev_traj_samples", 0) or 0) if history else 0),
            airflow_dry_learned=(history.get("airflow_dry_learned") if history else None),
            airflow_mai_learned=(history.get("airflow_mai_learned") if history else None),
            airflow_dev_learned=(history.get("airflow_dev_learned") if history else None),
            airflow_samples=(int(history.get("airflow_samples", 0) or 0) if history else 0),
            coherent_source=(_coherent_source if _coherent_n >= 2 else None))
        airflow = _airflow_ext.airflow
        extraction = _airflow_ext.extraction
        airwave_mode = _airflow_ext.airwave_mode
        air_ramp = _airflow_ext.air_ramp
        _dev_ramp = _airflow_ext.dev_ramp
        _dev_ramp_source = _airflow_ext.dev_ramp_source
        # The phase-entry summary must match the last development
        # heater target, including a learned development trajectory.
        _dev_heater_steps = [step["heater"] for step in _dev_ramp if "heater" in step]
        if _dev_heater_steps:
            heater_dev = float(_dev_heater_steps[-1])
            heater[2] = f"{heater_dev:.0f}%"

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
            decay_k=(float(ctx.maillard_ror_decay) if ctx is not None else 2.0),
            env_fc_entry_ror_c=(_env_timing.fc_entry_ror_c if _env_timing is not None else None))
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
            "heater_dry_pct":  heater_dry,          # requis par l'escalier progressif au replan
            "heater_maillard_pct": heater_maillard,
            "heater_dev_pct":  heater_dev,
            "heater_pre_fc_pct": heater_pre_fc,     # item C : palier pre-FC (FC appris)
            # geste préventif anti-flick au DE — appris ; 0.0 = pas de geste
            "heater_pre_de_pct": (heater_pre_de if _pre_de_active else 0.0),
            "pre_de_lead_sec":  _de_lead_sec,
            "pre_de_step_pct":  _de_step_pct,
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
            # Also the numeric input the weight-loss target reads back
            # (weight_loss_target_from_plan) — `or 0.0` because an unmeasured
            # lot carries None here and a format would raise.
            "Bean Humidity": f"{(humidity or 0.0):.1f}",
            "Water Activity Used": f"{bean.water_activity:.3f}" if bean.water_activity > 0.0 else "Not measured",
            "Ambient Temp": f"{_to_native(ambient_temp_c):.1f}",
            "Ambient Humidity": f"{ambient_humidity:.1f}",
            "Charge Temp":    f"{_to_native(charge_bt_temperature):.0f}",
            "End of Dry Temp": f"{_to_native(  dry_bt_temperature):.0f}",
            "First Crack Temp": f"{_to_native(fc_bt):.0f}",
            # ── Provenance ───────────────────────────────────────────────────
            # Two forms of the same fact, and the distinction is load-bearing.
            # The "... Source" entries are LABELS: operator-facing text, carrying
            # the sample count, printed by the PDF and free to be reworded.
            # "Source Keys" holds the stable machine tokens every piece of logic
            # must branch on. Matching display text is how the FC/charge
            # regression came to be gated on a condition that could never be
            # true — see _PlanSource.
            "FC Temp Source": fc_source.label,
            "Phase Timing Source": timing_source.label,
            "Drop Temp Source": drop_source.label,       # colour feedback
            "Heater Source": heater_source.label,        # per-phase burner
            "Heater FC Source": heater_fc_source.label,  # item C — palier pre-FC appris
            "Drop ROR Source": drop_ror_source.label,    # item A
            "Source Keys": {
                "fc":       fc_source.key,
                "timing":   timing_source.key,
                "drop":     drop_source.key,
                "drop_ror": drop_ror_source.key,
                "heater":   heater_source.key,
                "heater_fc": heater_fc_source.key,
                "dev_profile": _dev_ramp_source.key,
                "history_profile": (_coherent_source.key if _coherent_source else _SRC_GRID),
                "confidence": _conf_level,
            },
            "History Support": _conf_display,
            "History Profile Source": (_coherent_source.label if _coherent_source else "grid"),
            "History Reference Roast": ((history.get("coherent_profile") or {}).get("id")
                                         if history else None),
            "Prediction Error Summary": (history.get("prediction_error_summary") or {}
                                         if history else {}),  # P2 out-of-sample MAE
            "Plan Confidence": _conf_level,  # temporary internal compatibility
            # Seuils adaptatifs : bandes RoR relatives (sans unité) pour le
            # coach, deltas BT (unité native) pour l'adhérence EOR.
            "Plan Tolerances": {
                "level":        _conf_level,
                "ror_rel_ok":   round(0.15 * _tol_factor, 3),
                "ror_rel_warn": round(0.30 * _tol_factor, 3),
                "adher_ok":     round(3.0 * _tol_factor * _ror_scale, 1),
                "adher_warn":   round(7.0 * _tol_factor * _ror_scale, 1),
            },
            "Drop Temp":      f"{_to_native(drop_bt_temperature):.0f}",
            "Dry Phase":self.format_time(dry_time_min),
            "Dry Phase %": f"{dry_phase_percent:.1f}",
            "Maillard Phase":self.format_time(maillard_time_min),
            "Maillard Phase %": f"{maillard_phase_percent:.1f}",
            "FC Time":self.format_time(fc_time_min),
            "Development Phase":self.format_time(dev_time_min),
            "Development Phase %": f"{dev_phase_percent:.1f}",
            # Numeric twin of "Development Phase", which is a M:SS string and
            # unparseable downstream. With "Bean Humidity" it is what the
            # weight-loss target is read back from.
            "Development Phase (min)": f"{dev_time_min:.2f}",
            # What the cultivar family moved on the charge, so the operator sees
            # the prior instead of being quietly steered by it. Empty = none read.
            "Charge Family": _charge.family_name,
            "Charge Family Delta": f"{_charge.family_delta_c:+.0f}",
            "Roast Destination": self.roast_destination,
            "Total Time":self.format_time(drop_time_min),
            "Drum Speed (%) (Dry|Mai|Dev)": f"{' | '.join(drum_speed_pct)}",
            "Heater (%) (Dry|Mai|Dev)": f"{' | '.join(heater)}",
            "Airflow (%) (Dry|Mai|Dev)": f"{' | '.join(airflow)}",
            "Extraction (%) (Dry|Mai|Dev)": f"{' | '.join(extraction)}",
            "AirWave Mode (Dry|Mai|Dev)": f"{' | '.join(airwave_mode)}",
            "Target DTR": f"{dtr_achieved * 100.0:.1f}", # Resulting DTR — consequence of the retained durations, not a target (owner ruling 2026-08-04)
            "ROR Dry End":         f"{dry_ror_average * _ror_scale:.0f}",
            "ROR Dry Peak":        f"{dry_ror_peak * _ror_scale:.0f}",
            "Target ROR Maillard": f"{ror_maillard * _ror_scale:.1f}",
            # Valeur d'ARRIVÉE du Maillard, déduite de la décroissance en
            # puissance k de la machine — la moyenne seule ne dit pas où on
            # atterrit, et c'est l'atterrissage qui décide du FC.
            "Target ROR at FC": f"{ror_fc_c * _ror_scale:.1f}",
            "Maillard Conflict": _mai_conflict,   # "" | acceleration | crash | illegible
            ## Diagnostic seul : la courbe planifiée demande une pente que la
            ## machine ne tient pas. "" = rien à signaler. N'allonge PAS le
            ## séchage — voir le bloc _peak_ror_note pour pourquoi.
            "Peak ROR Warning": _peak_ror_note,
            "Target ROR Dev (Avg)": f"{dev_ror * _ror_scale:.1f}",
            "Target ROR at Drop":  f"{drop_ror * _ror_scale:.1f}",
            "Estimated TP":         f"{_to_native(tp_temperature):.0f}",
            "Heater at TP": f"{heater_tp:.0f}",
            # Anticipated Maillard→Dev heater steps, BT-triggered (native unit).
            # Consumed by TilauscopeAlarmFactory; empty when no heater control.
            "Heater Ramp": heater_ramp,
            "Dev Ramp": _dev_ramp,                     # trajectoire dev continue
            "Air Ramp": air_ramp,                      # montée airflow Maillard (mi-Mai→FC)
            "Dev Profile Source": _dev_ramp_source.label,  # learned (n=N) | default
            "FC Anticipation (s)": f"{fc_anticipation_sec:.0f}",
            "Target Agtron": target_roast_category, # Use the determined category
            # What the plan promises on the scale, so the roast can be validated
            # after the fact: the lot's water plus the dry matter the colour and
            # the development burn off.
            "Target Weight Loss": (
                f"{_wl_target.target:.1f}" if (_wl_target := weight_loss_target(
                    target_roast_category, moisture_pct=(humidity or 0.0),
                    dev_time_min=dev_time_min)) else "N/A"),
            # Point 8: surface roaster capability flags so the UI/alarm factory
            # can adapt their behaviour without importing roasters.py.
            "Roaster": ctx.display_name if ctx else "Unknown",
            "Preheat Profile Available": ctx.supports_preheat_profiles if ctx else False,
            "Profile Replay Available":  ctx.supports_profile_replay  if ctx else False,
            "Drum Variable Speed":        _drum_variable,
            "notes": history["notes"] if history else None,
            "actions": ((((history["actions"] or []) if history else [])
                         + _plan_notes
                         + _heater_authority
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
        """Escalier heater PROGRESSIF ancré MI-PHASE (item C,
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
        # Feu de séchage TENU jusqu'à ~30 s du DRY END (doctrine Tilau : le feu au DE
        # vient du réglage initial, on n'y touche pas avant). Les 30 s sont converties
        # en BT par la pente MOYENNE du séchage (pas une constante), légèrement
        # surestimée donc on lâche ~1 °C trop tôt — dans le sens de l'anticipation.
        # Valeur apprise AU DRY END : point d'arrivée du séchage, pas un geste unique
        # — 4e point d'ancrage de l'escalier, entre la médiane de séchage et le mi-Maillard.
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
            # ── Émission PAR VALEUR (marches ≤ 5 %, étude 3) ──────────────────
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

            # Heater ramp rebuilt avec le même escalier progressif TP→pre-FC que la
            # génération (helper partagé). Au replan « tp » (swap d'ancre seul) on n'y
            # touche pas : l'escalier initial est déjà correct.
            heater_ramp: list[dict] = []
            if milestone != "tp" and ctx.get("has_heater"):
                heater_ramp = self._build_heater_ramp_c(
                    float(a_tp["bt"]), float(a_dry["bt"]), float(a_fc["bt"]),
                    float(ctx["ror_maillard_c"]), float(ctx["fc_anticipation_sec"]),
                    float(ctx.get("heater_res", 1.0)),
                    float(ctx.get("heater_dry_pct", 0.0)),
                    float(ctx.get("heater_maillard_pct", 0.0)),
                    # item C : palier pre-FC (FC appris) ; repli dev
                    # pour les vieux dicts de plan sans la clé.
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
            new_plan["End of Dry Temp"]      = f"{_nat(float(a_dry['bt'])):.0f}"
            new_plan["First Crack Temp"]     = f"{_nat(float(a_fc['bt'])):.0f}"
            new_plan["Estimated TP"]         = f"{_nat(float(a_tp['bt'])):.0f}"
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
                new_plan["Heater Ramp"] = heater_ramp   # préserve l'escalier au replan TP
            # Dev Ramp : les consignes de leviers apprises ne bougent
            # pas, mais leurs seuils BT suivent les ancres FC/DROP re-fittées
            # (chaque étage garde sa fraction "_f" ; même géométrie qu'à la
            # génération : fc → drop−3°).
            if plan.get("Dev Ramp"):
                _fc_c, _drop_c = float(a_fc["bt"]), float(a_drop["bt"])
                new_plan["Dev Ramp"] = [
                    {**_e, "bt": round(_nat(_fc_c + (_drop_c - 3.0 - _fc_c)
                                            * float(_e.get("_f", 0.5))), 1)}
                    for _e in plan["Dev Ramp"]]
            # Air Ramp (Maillard) : chaque palier garde sa fraction "_af"
            # (mi-Maillard→pre-FC) et son seuil BT suit les ancres re-fittées —
            # même traitement que le Dev Ramp, plus de re-répartition uniforme
            # qui déplaçait les paliers hors de leur place réelle.
            if plan.get("Air Ramp"):
                _mid_c = (float(a_dry["bt"]) + float(a_fc["bt"])) / 2.0
                _lead_c = max(0.0, float(ctx["ror_maillard_c"])) * float(ctx["fc_anticipation_sec"]) / 60.0
                _pfc_c = max(_mid_c + 1.0, float(a_fc["bt"]) - _lead_c)
                # Les crans d'approche du DRY END ("_ade", en °C sous le jalon)
                # suivent l'ancre DRY END, pas le cadre mi-Maillard→pre-FC.
                new_plan["Air Ramp"] = [
                    ({**_e, "bt": round(_nat(float(a_dry["bt"]) - float(_e["_ade"])), 1)}
                     if "_ade" in _e else
                     {**_e, "bt": round(_nat(_mid_c + (_pfc_c - _mid_c) * float(_e.get("_af", 0.5))), 1)})
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
        # Valeur d'ENTRÉE, pas la colonne Maillard : celle-ci est la MOYENNE
        # d'une descente, et l'escalier brûleur a déjà commencé à la jouer avant
        # le DE (le feu de séchage est tenu jusqu'à ~30 s du jalon, puis lâché
        # par paliers). Poser la moyenne ici faisait chuter le brûleur d'un cran
        # de trop au DE, puis l'escalier le faisait remonter — un geste que
        # personne ne peut exécuter. On pose ce que l'escalier TIENT au DE.
        _de_bt = self._parse_val("End of Dry Temp")
        _de_held = [int(s["heater"]) for s in (self.plan.get("Heater Ramp") or [])
                    if float(s["bt"]) <= _de_bt]
        _de_burner = ((_de_held[-1] if _de_held else heaters[0])
                      if self.plan.get("Heater Ramp") else heaters[1])
        self._add_row(alarms, 1, -1,-1, self.EVENTS.get("DRY END"), 0.      , -3       , 2, 0.0, self.ACTION_LIST.get("Slider Burner"), 0,    f"{_de_burner}"   )
        self._add_row(alarms, 1, -1,-1, self.EVENTS.get("DRY END"), 1.      , -3       , 2, 0.0, self.ACTION_LIST.get("Slider Air"),    0,    f"{airflows[1]}"   )
        # Doctrine tambour : aucune ligne tambour in-roast — posé une fois à la
        # CHARGE (setup), ne bouge qu'au DROP (refroidissement).
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

        # 2c. RAMPE AIRFLOW DE MAILLARD (mi-Maillard → pre-FC)
        # Même mécanique que la rampe brûleur : seuil BT, armé après DRY END.
        # Elle n'était pas exportée — l'air restait sur sa valeur de Maillard
        # jusqu'au FC alors que le plan demande de l'ouvrir progressivement dès
        # l'arrivée du brunissement, et le PDF, lui, dessinait bien la montée.
        air_ramp = self.plan.get("Air Ramp") or []
        for step in air_ramp:
            self._add_row(
                alarms, 1, -1, -1, self.EVENTS.get("DRY END"), 0., 1, 1,
                float(step["bt"]), self.ACTION_LIST.get("Slider Air"), 0,
                f"{int(step['airflow'])}")

        # Alerte First Crack (FC START)
        # ── Valeurs d'ENTRÉE de phase, pas valeurs de fin ────────────────────
        # Quand la Dev Ramp est exportée (plus bas), le FC n'est plus l'endroit
        # où l'on pose le réglage de développement : c'est la rampe qui l'amène,
        # palier par palier. Poser ici la colonne DEV — qui vaut désormais la
        # DERNIÈRE valeur de la Dev Ramp — sauterait d'un coup à l'arrivée puis
        # ferait redescendre les paliers, exactement le saut brutal que la rampe
        # existe pour éviter. On pose donc ce que la trajectoire TIENT au FC :
        # le dernier palier de la rampe d'air pour l'airflow, la valeur de
        # Maillard pour l'AirWave, le dernier palier de la rampe brûleur pour le
        # filet de sécurité. Même lecture que la table d'entrée de phase du PDF
        # (_entry_settings). Sans Dev Ramp, rien ne suivrait : on garde alors la
        # colonne DEV, seule valeur qui sera jamais posée.
        dev_ramp = self.plan.get("Dev Ramp") or []
        _fc_burner = (int(heater_ramp[-1]["heater"]) if (dev_ramp and heater_ramp)
                      else heaters[2])
        _fc_air = (int(air_ramp[-1]["airflow"]) if (dev_ramp and air_ramp)
                   else (airflows[1] if dev_ramp else airflows[2]))
        _fc_ext = extractions[1] if dev_ramp else extractions[2]
        # Le step burner à FC n'est qu'un filet de sécurité : negguard sur le
        # dernier step de la rampe — il ne tire que si le seuil BT anticipé
        # n'a jamais été atteint (FC précoce, sonde en retard). Offset +1 s :
        # une ligne temporelle à offset 0 ne tire jamais (bloc offset sauté).
        self._add_row(alarms, 1, -1, pre_fc_idx, self.EVENTS.get("FC START"), 1.      , -3       , 2, 0.0, self.ACTION_LIST.get("Slider Burner"), 0,    f"{_fc_burner}"   )
        self._add_row(alarms, 1, -1,-1, self.EVENTS.get("FC START"), 1.      , -3       , 2, 0.0, self.ACTION_LIST.get("Slider Air"),    0,    f"{_fc_air}"   )
        # Pas de ligne tambour à FC START (doctrine setup).
        if self._airwave_present:
            self._add_row(alarms, 1, -1,-1, self.EVENTS.get("FC START"), 3., -3, 2, 0.0, self.ACTION_LIST.get("Slider Damper"),          0, f"{_fc_ext}")
            self._add_row(alarms, 1, -1,-1, self.EVENTS.get("FC START"), 5., -3, 2, 0.0, self.ACTION_LIST.get("Difluid Airwave command"), 0, "MODE EXT")
        self._add_row(alarms, 1, -1,-1, self.EVENTS.get("FC START"), 4.      , -3       , 2, 0.0, self.ACTION_LIST.get("TilauScope Ambient command"),   0,    "STOP"   )

        # 2d. RAMPE DE DÉVELOPPEMENT (FC → drop)
        # Seuils BT armés après FC START. Un palier peut porter plusieurs
        # leviers : le feu descend pendant que l'air s'ouvre pour soutenir la
        # réaction (doctrine Tilau) — les deux gestes tombent au même seuil et
        # font donc deux lignes. Le damper ne sort que si l'AirWave est là, comme
        # partout ailleurs dans cette fabrique.
        _dev_actions = (("heater", "Slider Burner"), ("airflow", "Slider Air"),
                        ("extraction", "Slider Damper"))
        for step in dev_ramp:
            for _key, _action in _dev_actions:
                if _key not in step:
                    continue
                if _key == "extraction" and not self._airwave_present:
                    continue
                self._add_row(
                    alarms, 1, -1, -1, self.EVENTS.get("FC START"), 0., 1, 1,
                    float(step["bt"]), self.ACTION_LIST.get(_action), 0,
                    f"{int(step[_key])}")

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

    #: Unicode family registered in place of FPDF's latin-1 core fonts. The core
    #: fonts RAISE on any character outside latin-1, which took down the whole
    #: plan for 18 of the 35 shipped languages — a single word like CHARGE
    #: translated to "ÚČTOVAT" (cs) or "投豆" (zh) was enough. A registered
    #: TrueType font renders an unknown glyph blank instead of raising, so the
    #: worst case becomes a gap in the page rather than no page at all.
    #: DejaVu Sans is proportional like the Helvetica it replaces, carries the
    #: three styles the report uses, and is freely redistributable
    #: (licenses/DejaVu-Fonts.txt).
    _FONT: Final[str] = "tilauplan"
    #: fpdf style code → (bold, italic), resolved through tilauscope.text_shaping
    #: so the report, the label sheets and the Niimbot bitmaps all use one face.
    _FONT_STYLES: Final[dict] = {'': (False, False), 'B': (True, False),
                                 'I': (False, True)}
    #: Class-level default so the set_font override is safe even if FPDF's own
    #: __init__ reaches it before ours has run.
    _family: str = "helvetica"

    def __init__(self, orientation="P", unit="mm", format="A4", temp_unit="C",
                 roaster_ctx: "RoasterContext | None" = None):
        super().__init__(orientation, unit, format)
        self.mode = temp_unit
        self._target = ""
        self._roaster = ""
        self._destination = ""
        self._roaster_ctx: "RoasterContext | None" = roaster_ctx
        self._family: str = self._register_unicode_font()

    def _register_unicode_font(self) -> str:
        """Register the Unicode family; fall back to the core font if absent.

        A source checkout without the bundled fonts must still produce a plan,
        so a missing file degrades to 'helvetica' rather than raising — the same
        report as before, with the same latin-1 limit.
        """
        try:
            for style, (bold, italic) in self._FONT_STYLES.items():
                path = text_shaping.sans_path(bold=bold, italic=italic)
                if path is None:
                    _logd.warning(
                        "RoastPlanPDF: body face missing, falling back to a latin-1 core font")
                    return "helvetica"
                self.add_font(self._FONT, style, str(path))
            cjk = text_shaping.cjk_path()
            if cjk is not None:
                self.add_font("tilauplancjk", "", str(cjk))
                self.set_fallback_fonts(["tilauplancjk"])
        except Exception as e:      # never let typography stop a roast plan
            _logd.warning("RoastPlanPDF: Unicode font unavailable (%s), using core font", e)
            return "helvetica"
        return self._FONT

    # ── Bidirectional scripts ────────────────────────────────────────────────
    # The pass itself lives in tilauscope.text_shaping: the Niimbot labels need
    # exactly the same treatment (Pillow shapes no better than fpdf), and two
    # copies would drift.
    _RTL_RANGES: Final[tuple] = text_shaping.RTL_RANGES
    _ARABIC_RANGES: Final[tuple] = text_shaping.ARABIC_RANGES

    @classmethod
    def _bidi(cls, text: Any) -> Any:
        """Join and reorder Arabic/Persian/Hebrew — see text_shaping.shape_bidi."""
        return text_shaping.shape_bidi(text)

    @staticmethod
    def _in_ranges(ch: str, ranges: tuple) -> bool:
        return text_shaping.in_ranges(ch, ranges)

    # Routed centrally, like set_font: one missed call site would leave a single
    # label unjoined, which is exactly the defect nobody notices in review.
    def _bidi_call(self, args: tuple, kwargs: dict) -> "tuple[tuple, dict]":
        """Apply the bidi pass whichever way the caller passed the string.

        cell/multi_cell/text all take it third; it can also arrive as ``text=``
        or as the deprecated ``txt=`` alias fpdf still accepts and rewrites. A
        signature that assumed one form broke the graph labels, which use
        ``txt=``, so the argument is located rather than assumed.
        """
        for key in ("text", "txt"):
            if key in kwargs:
                kwargs[key] = self._bidi(kwargs[key])
                return args, kwargs
        if len(args) > 2:
            mutable = list(args)
            mutable[2] = self._bidi(mutable[2])
            return tuple(mutable), kwargs
        return args, kwargs

    def cell(self, *args, **kwargs):            # type: ignore[override]
        args, kwargs = self._bidi_call(args, kwargs)
        return super().cell(*args, **kwargs)

    def multi_cell(self, *args, **kwargs):      # type: ignore[override]
        args, kwargs = self._bidi_call(args, kwargs)
        return super().multi_cell(*args, **kwargs)

    def text(self, *args, **kwargs):            # type: ignore[override]
        args, kwargs = self._bidi_call(args, kwargs)
        return super().text(*args, **kwargs)

    def output(self, *args, **kwargs):   # type: ignore[override]
        """Write the document, then release the font file handles.

        fpdf2 keeps every registered TrueType open — fontTools reads it lazily
        for subsetting — and never closes it. A session generating several plans
        would accumulate descriptors for nothing. Closing after `output` is safe
        because subsetting is done by then; the instance is single-use
        afterwards, which is how the report is built.
        """
        try:
            return super().output(*args, **kwargs)
        finally:
            for font in getattr(self, 'fonts', {}).values():
                tt = getattr(font, 'ttfont', None)
                if tt is not None:
                    try:
                        tt.close()
                    except Exception:   # noqa: S110 - releasing a handle must never fail a report
                        pass

    def set_font(self, family=None, style="", size=0):   # type: ignore[override]
        """Route every call to the registered Unicode family.

        Overridden rather than edited at ~38 call sites: a single missed site
        would reintroduce the crash for one string only, which is exactly the
        kind of defect that ships unnoticed.
        """
        super().set_font(self._family if family else family, style, size)

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
        _sub = f"({self._target})" if not self._destination else f"({self._target} - {self._destination})"
        self.cell(0, 10, _sub, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
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
                text=label_txt,
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

    @staticmethod
    def _phase_pct(raw: Any, col: int) -> "float | None":
        """One phase value out of a 'Dry | Mai | Dev' summary string."""
        try:
            return float(str(raw).split('|')[col].strip().rstrip('%'))
        except (ValueError, IndexError, AttributeError):
            return None

    def _control_trajectories(self, plan_data: dict) -> "tuple[list, list, dict]":
        """Heater and airflow as (time_min, percent) points, plus milestones.

        Both are STAIRCASES: a setting is posted once and held until the next
        change. Drawing a slope between two settings would picture a continuous
        knob movement that never happens — the operator makes one step, then
        waits to read its effect.

        The sequence mirrors what the assistant actually applies (see
        ``roast_asssistant._ap_phase_targets``), not the phase summary table:
        the burner holds its charge value until the anticipated ramp takes over,
        then the Dev Ramp carries it through development; airflow is posted at
        each phase, refined by the Maillard Air Ramp, then also carried by the
        Dev Ramp. Reading the summary instead would draw three flat plateaus and
        hide every gesture the plan actually asks for.
        """
        curve = plan_data.get("bt_plan_curve") or {}
        times = list(curve.get("time_min") or [])
        bts = list(curve.get("bt_plan") or [])
        if len(times) < 2 or len(times) != len(bts):
            return [], [], {}

        # Milestones by stable key, never by translated label.
        wps = {w.get("key"): w for w in (curve.get("waypoints") or [])}

        def _wp_t(key: str) -> float:
            try:
                return float(wps.get(key, {}).get("time_min", 0.0) or 0.0)
            except (TypeError, ValueError):
                return 0.0

        t_end = float(times[-1])
        milestones = {"dry_end": _wp_t("dry_end"), "fc_start": _wp_t("fc_start"),
                      "tp": _wp_t("tp"), "t_end": t_end}

        # BT -> time, scanning forward from the TURNING POINT: bean temperature
        # falls to TP before it rises, so a scan from t=0 would resolve a
        # Maillard threshold against the charge descent and place the step at
        # the wrong end of the roast.
        i_tp = min(range(len(bts)), key=lambda i: bts[i])

        def t_at_bt(target: float) -> float:
            for i in range(i_tp + 1, len(bts)):
                if bts[i] >= target:
                    b0, b1 = bts[i - 1], bts[i]
                    if b1 > b0:
                        f = (target - b0) / (b1 - b0)
                        return times[i - 1] + f * (times[i] - times[i - 1])
                    return times[i]
            return t_end

        def _collect(ramp_key: str, value_key: str, out: list) -> None:
            for e in (plan_data.get(ramp_key) or []):
                if not isinstance(e, dict) or value_key not in e:
                    continue
                try:
                    out.append((t_at_bt(float(e["bt"])), float(e[value_key])))
                except (KeyError, TypeError, ValueError):
                    continue

        heater: list = []
        h_dry = self._phase_pct(plan_data.get("Heater (%) (Dry|Mai|Dev)", ""), 0)
        if h_dry is not None:
            heater.append((0.0, h_dry))
        _collect("Heater Ramp", "heater", heater)
        _collect("Dev Ramp", "heater", heater)

        airflow: list = []
        a_dry = self._phase_pct(plan_data.get("Airflow (%) (Dry|Mai|Dev)", ""), 0)
        if a_dry is not None:
            airflow.append((0.0, a_dry))
        a_mai = self._phase_pct(plan_data.get("Airflow (%) (Dry|Mai|Dev)", ""), 1)
        if a_mai is not None and milestones["dry_end"] > 0.0:
            airflow.append((milestones["dry_end"], a_mai))
        _collect("Air Ramp", "airflow", airflow)
        _collect("Dev Ramp", "airflow", airflow)

        def _tidy(points: list) -> list:
            """Chronological, and one value per instant — a later entry for the
            same time wins, so a ramp step overrides the phase feedforward it
            lands on rather than drawing a spike."""
            points.sort(key=lambda p: p[0])
            out: list = []
            for t, v in points:
                if out and abs(out[-1][0] - t) < 1e-6:
                    out[-1] = (t, v)
                elif not out or out[-1][1] != v:
                    out.append((t, v))
            return out

        return _tidy(heater), _tidy(airflow), milestones

    def _entry_settings(self, plan_data: dict) -> "list[tuple[str, list[str]]]":
        """Rows for the phase-entry table: what each lever must READ when the
        milestone is crossed — at CHARGE, at DRY END, at FIRST CRACK.

        Deliberately not the phase average. A figure like 59 % for Maillard is
        the mean of a descent, and the operator never dials a mean; reading it
        as an instruction posts the middle of the ramp at the start of the
        phase, half a phase too low too early. The entry values are read off the
        same trajectories the section 5 chart draws, so table and chart cannot
        disagree.

        The burner can therefore show the same value at CHARGE and at DRY END.
        That is the doctrine made visible: the drying fire is held through dry
        end, and the descent starts just after it.
        """
        heater, airflow, ms = self._control_trajectories(plan_data)
        marks = [0.0, float(ms.get("dry_end") or 0.0), float(ms.get("fc_start") or 0.0)]
        ctx = self._roaster_ctx

        def _held(points: list, t: float) -> "float | None":
            held = None
            for pt, pv in points:
                if pt <= t + 1e-9:
                    held = pv
                else:
                    break
            return held

        def _fmt(values: list, label_fn) -> list:
            out = []
            for v in values:
                if v is None:
                    out.append("N/A")
                    continue
                raw = f"{v:.0f}%"
                out.append(self._fmt_ctrl(raw, label_fn) if ctx is not None else raw)
            return out

        def _phase(key: str, cols: "tuple[int, int, int]") -> "list[float | None]":
            parts = str(plan_data.get(key, "")).split('|')
            out: "list[float | None]" = []
            for c in cols:
                try:
                    out.append(float(parts[c].strip().rstrip('%')))
                except (ValueError, IndexError):
                    out.append(None)
            return out

        rows: "list[tuple[str, list[str]]]" = []
        if heater:
            rows.append((QApplication.translate("tilauscope_roast_plan", "Heater") + " (%)",
                         _fmt([_held(heater, t) for t in marks],
                              ctx.pct_to_heater_label if ctx else None)))
        if airflow:
            rows.append((QApplication.translate("tilauscope_roast_plan", "Airflow") + " (%)",
                         _fmt([_held(airflow, t) for t in marks],
                              ctx.pct_to_airflow_label if ctx else None)))
        # Drum is a SETUP value: one setting for the whole roast, so its three
        # columns are the same figure by construction, not by accident.
        _drum = _phase("Drum Speed (%) (Dry|Mai|Dev)", (0, 1, 2))
        if any(v is not None for v in _drum):
            rows.append((QApplication.translate("tilauscope_roast_plan", "Drum Speed") + " (%)",
                         _fmt(_drum, ctx.pct_to_drum_label if ctx else None)))
        # AirWave: posted at CHARGE and at DRY END, then carried by the Dev Ramp
        # — so the value at FC entry is still the Maillard one, as for airflow.
        if str(plan_data.get("Extraction (%) (Dry|Mai|Dev)", "")).strip():
            _ext = _phase("Extraction (%) (Dry|Mai|Dev)", (0, 1, 1))
            rows.append((QApplication.translate("tilauscope_roast_plan", "AirWave")
                         + " (% " + QApplication.translate("tilauscope_roast_plan", "Fan") + ")",
                         _fmt(_ext, None)))
        return rows

    def _control_gestures(self, plan_data: dict) -> "list[dict]":
        """Every lever change the plan asks for, in order.

        One row per gesture rather than one per lever: at the machine the
        question is always "what do I do next", and two levers moving at the
        same threshold are two distinct hands on two distinct knobs.
        """
        heater, airflow, ms = self._control_trajectories(plan_data)
        if not heater and not airflow:
            return []
        curve = plan_data.get("bt_plan_curve") or {}
        times = list(curve.get("time_min") or [])
        bts = list(curve.get("bt_plan") or [])

        def bt_at(t: float) -> "float | None":
            for i in range(len(times)):
                if times[i] >= t:
                    return bts[i]
            return bts[-1] if bts else None

        t_de = float(ms.get("dry_end") or 0.0)
        t_fc = float(ms.get("fc_start") or 0.0)
        out: "list[dict]" = []
        for points, lever in ((heater, QApplication.translate("tilauscope_roast_plan", "Heater")),
                              (airflow, QApplication.translate("tilauscope_roast_plan", "Airflow"))):
            for i in range(1, len(points)):
                out.append({"t": points[i][0], "lever": lever,
                            "frm": points[i - 1][1], "to": points[i][1],
                            "bt": bt_at(points[i][0])})
        out.sort(key=lambda g: g["t"])
        for g in out:
            g["phase"] = (QApplication.translate("Label", "Dry") if g["t"] < t_de
                          else QApplication.translate("Label", "Maillard") if g["t"] < t_fc
                          else QApplication.translate("Label", "Development"))
        return out

    @staticmethod
    def _mmss(t_min: float) -> str:
        total = int(round(float(t_min) * 60.0))
        return f"{total // 60:d}:{total % 60:02d}"

    def draw_control_ramp_graph(self, plan_data: dict, x_pos: float, y_pos: float,
                                 width: float, height: float) -> bool:
        """Heater (red) and airflow (blue) setpoints over the whole roast.

        Returns False when the plan carries no trajectory to draw, so the caller
        can skip the section rather than print an empty frame.
        """
        heater, airflow, ms = self._control_trajectories(plan_data)
        if not heater and not airflow:
            return False

        t_end = float(ms.get("t_end") or 0.0)
        if t_end <= 0.0:
            return False

        def sx(t: float) -> float:
            return x_pos + (max(0.0, min(t_end, t)) / t_end) * width

        def sy(pct: float) -> float:
            return y_pos + height - (max(0.0, min(100.0, pct)) / 100.0) * height

        # ── Phase bands (same palette as the BT/RoR graph, so the two pages
        # read as one document) ──────────────────────────────────────────────
        for name, t0, t1, rgb in (
            ("DRY", 0.0, ms.get("dry_end", 0.0), (255, 252, 230)),
            ("MAILLARD", ms.get("dry_end", 0.0), ms.get("fc_start", 0.0), (255, 240, 210)),
            ("DEVELOPMENT", ms.get("fc_start", 0.0), t_end, (245, 230, 220)),
        ):
            if t1 <= t0:
                continue
            self.set_fill_color(*rgb)
            self.rect(sx(t0), y_pos, sx(t1) - sx(t0), height, style="F")

        # ── Grid: every 20 % and every 2 min ─────────────────────────────────
        self.set_draw_color(205, 205, 205)
        self.set_line_width(0.15)
        self.set_dash_pattern()
        self.set_font("Helvetica", "", 7)
        self.set_text_color(90, 90, 90)
        for pct in range(0, 101, 20):
            y = sy(pct)
            self.line(x_pos, y, x_pos + width, y)
            self.text(x_pos - 8, y + 1.2, f"{pct}%")
        _t = 0.0
        while _t <= t_end + 1e-9:
            x = sx(_t)
            self.line(x, y_pos, x, y_pos + height)
            self.text(x - 3, y_pos + height + 4, f"{int(_t)}'")
            _t += 2.0

        # ── Milestone verticals (DRY END, FC) ────────────────────────────────
        self.set_line_width(0.4)
        self.set_dash_pattern(dash=1.2, gap=1.2)
        self.set_draw_color(120, 120, 120)
        for key, label in (("dry_end", QApplication.translate("Button", "DRY END")),
                           ("fc_start", QApplication.translate("Button", "FC START"))):
            t = float(ms.get(key) or 0.0)
            if t <= 0.0 or t >= t_end:
                continue
            self.line(sx(t), y_pos, sx(t), y_pos + height)
            self.set_font("Helvetica", "B", 6)
            self.set_text_color(110, 110, 110)
            self.text(sx(t) + 1, y_pos + 3.5, label)
        self.set_dash_pattern()

        def _staircase(points: list, rgb: tuple, label_above: bool) -> None:
            """Hold-then-step: horizontal to the next change, then vertical to
            the new value. The last value is held to the drop."""
            if not points:
                return
            self.set_draw_color(*rgb)
            self.set_line_width(0.9)
            self.set_dash_pattern()
            last_label_x = -99.0
            for i, (t, v) in enumerate(points):
                t_next = points[i + 1][0] if i + 1 < len(points) else t_end
                self.line(sx(t), sy(v), sx(t_next), sy(v))
                if i + 1 < len(points):
                    self.line(sx(t_next), sy(v), sx(t_next), sy(points[i + 1][1]))
                # Label sparsely: a value every 9 mm stays readable, and the
                # operator reads levels off the axis anyway.
                if sx(t) - last_label_x >= 9.0:
                    self.set_font("Helvetica", "B", 6)
                    self.set_text_color(*rgb)
                    self.text(sx(t) + 0.6,
                              sy(v) - 1.6 if label_above else sy(v) + 3.4,
                              f"{v:.0f}")
                    last_label_x = sx(t)
            # The value held to the DROP, in the right margin: it is the one the
            # operator finishes on, and the spacing rule above would drop it
            # whenever the last steps bunch up in development. Outside the plot
            # so the two curves cannot collide here even when they cross.
            self.set_font("Helvetica", "B", 7)
            self.set_text_color(*rgb)
            self.text(x_pos + width + 1.5, sy(points[-1][1]) + 1.0,
                      f"{points[-1][1]:.0f}%")

        _RED = (200, 40, 40)
        _BLUE = (40, 90, 200)
        _staircase(airflow, _BLUE, label_above=False)
        _staircase(heater, _RED, label_above=True)

        # ── Border ───────────────────────────────────────────────────────────
        self.set_draw_color(80, 80, 80)
        self.set_line_width(0.3)
        self.set_dash_pattern()
        self.rect(x_pos, y_pos, width, height, style="D")

        # ── Legend ───────────────────────────────────────────────────────────
        leg_y = y_pos + height + 10
        self.set_font("Helvetica", "", 8)
        self.set_draw_color(*_RED)
        self.set_line_width(0.9)
        self.line(x_pos, leg_y, x_pos + 10, leg_y)
        self.set_text_color(0, 0, 0)
        self.text(x_pos + 13, leg_y + 2.5,
                  QApplication.translate("tilauscope_roast_plan", "Heater (%)"))
        self.set_draw_color(*_BLUE)
        self.line(x_pos + 55, leg_y, x_pos + 65, leg_y)
        self.set_text_color(0, 0, 0)
        self.text(x_pos + 68, leg_y + 2.5,
                  QApplication.translate("tilauscope_roast_plan", "Airflow (%)"))
        self.set_text_color(0, 0, 0)
        return True

    def _draw_step_sequence(self, plan_data: dict) -> None:
        """The heat ladder as a checklist instead of a run-on line of pairs.

        This is the moved 'Heater ramp (anticipated)' and 'Heater source' from
        section 4: the same data, one gesture per row, next to the chart it
        belongs with.
        """
        gestures = self._control_gestures(plan_data)
        if not gestures:
            return
        _HEAD = (225, 225, 225)
        _ALT = (246, 246, 246)
        self.set_font('helvetica', 'B', 10)
        self.set_text_color(0, 0, 0)
        self.cell(0, 6, QApplication.translate("tilauscope_roast_plan", "Step sequence"),
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(0.5)

        cols = [14, 20, 22, 28, 34, 44]
        heads = ["#",
                 QApplication.translate("tilauscope_roast_plan", "Time"),
                 QApplication.translate("Label", "BT"),
                 QApplication.translate("tilauscope_roast_plan", "Lever"),
                 QApplication.translate("tilauscope_roast_plan", "Change"),
                 QApplication.translate("tilauscope_roast_plan", "Phase")]
        self.set_font('helvetica', 'B', 8.5)
        self.set_fill_color(*_HEAD)
        for w, h in zip(cols, heads):
            self.cell(w, 5.5, h, 1, align='C', fill=True)
        self.ln()

        self.set_font('helvetica', '', 8.5)
        for i, g in enumerate(gestures):
            self.ensure_space(12)
            self.set_fill_color(*(_ALT if i % 2 else (255, 255, 255)))
            bt = f"{g['bt']:.0f}°{self.mode}" if g.get('bt') is not None else "-"
            row = [str(i + 1), self._mmss(g['t']), bt, g['lever'],
                   f"{g['frm']:.0f} -> {g['to']:.0f}%", g['phase']]
            for w, v in zip(cols, row):
                self.cell(w, 5.0, v, 1, align='C', fill=True)
            self.ln()

        # Provenance, kept with the ladder it qualifies.
        _hsrc = str(plan_data.get("Heater Source", "grid"))
        _hfc = str(plan_data.get("Heater FC Source", "grid"))
        if _hfc != "grid":
            _hsrc = f"{_hsrc}  |  pre-FC: {_hfc}"
        _lead = plan_data.get("FC Anticipation (s)", "")
        self.ln(1.5)
        self.set_font('helvetica', '', 8.5)
        _line = QApplication.translate("tilauscope_roast_plan", "Heater source") + f": {_hsrc}"
        if _lead:
            _line += "   |   " + QApplication.translate(
                "tilauscope_roast_plan", "last step {0} s before FC").format(_lead)
        self.multi_cell(0, 5, _line, new_x=XPos.LMARGIN, new_y=YPos.NEXT, border=0)
        self.ln(2)

    def _draw_plan_recap(self, plan_data: dict) -> None:
        """The five figures worth carrying in your head, under the sequence:
        where you charge, where you drop, and how long each phase should take."""
        _deg = f" °{self.mode}"
        rows = [
            [(QApplication.translate("Label", "CHARGE"), f"{plan_data.get('Charge Temp', 'N/A')}{_deg}"),
             (QApplication.translate("Label", "DROP"), f"{plan_data.get('Drop Temp', 'N/A')}{_deg}"),
             (QApplication.translate("Button", "FC START"), f"{plan_data.get('First Crack Temp', 'N/A')}{_deg}"),
             (QApplication.translate("tilauscope_roast_plan", "Total time"), str(plan_data.get('Total Time', 'N/A')))],
            [(QApplication.translate("Label", "Dry"), f"{plan_data.get('Dry Phase', 'N/A')} ({plan_data.get('Dry Phase %', '-')}%)"),
             (QApplication.translate("Label", "Maillard"), f"{plan_data.get('Maillard Phase', 'N/A')} ({plan_data.get('Maillard Phase %', '-')}%)"),
             (QApplication.translate("Label", "Development"), f"{plan_data.get('Development Phase', 'N/A')} ({plan_data.get('Development Phase %', '-')}%)"),
             (QApplication.translate("tilauscope_roast_plan", "Resulting DTR (%)"), f"{plan_data.get('Target DTR', 'N/A')}%")],
        ]
        self.ensure_space(30)
        self.set_font('helvetica', 'B', 10)
        self.set_text_color(0, 0, 0)
        self.cell(0, 6, QApplication.translate("tilauscope_roast_plan", "At a glance"),
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(0.5)
        widths = [40, 40, 42, 40]
        for row in rows:
            self.set_font('helvetica', '', 7.5)
            self.set_text_color(110, 110, 110)
            for w, (k, _v) in zip(widths, row):
                self.cell(w, 4, "  " + k.upper(), 0, align='L')
            self.ln()
            self.set_font('helvetica', 'B', 10)
            self.set_text_color(0, 0, 0)
            for w, (_k, v) in zip(widths, row):
                self.cell(w, 6, "  " + str(v), 0, align='L')
            self.ln(7)
        self.set_text_color(0, 0, 0)

    def ensure_space(self, needed_height:int):
        if self.get_y() + needed_height > self.page_break_trigger:
            self.add_page()

    @staticmethod
    def _destination_label(key: Any) -> str:
        """Human name of the brewing destination the plan was built for."""
        return {
            "filter":   QApplication.translate("tilauscope_roast_plan", "Filter"),
            "omni":     QApplication.translate("tilauscope_roast_plan", "Omni"),
            "espresso": QApplication.translate("tilauscope_roast_plan", "Espresso"),
        }.get(str(key or "").lower(), "")

    def create_pdf_report(self, plan_data:dict, graph_data, crashes, flicks)->None:
        """Fills the PDF with the calculated roast plan data in a clear, structured format,
        including phase percentages."""

        self._target = plan_data["Target Roast Level"]
        self._roaster = plan_data["Roaster"]
        self._destination = self._destination_label(plan_data.get("Roast Destination"))

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
            (QApplication.translate("tilauscope_roast_plan","Intended use"), self._destination),
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
            (QApplication.translate("tilauscope_roast_plan","Drop RoR source"), plan_data.get("Drop ROR Source", "grid")),  # item A
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
            (QApplication.translate("tilauscope_roast_plan","Target weight loss (%)"), plan_data.get("Target Weight Loss")),
            (QApplication.translate("tilauscope_roast_plan","History support"), plan_data.get("History Support", "grid only")),
            (QApplication.translate("tilauscope_roast_plan","History profile"), plan_data.get("History Profile Source", "grid")),
            (QApplication.translate("tilauscope_roast_plan","Resulting DTR (%)"), plan_data.get("Target DTR")),
            (QApplication.translate("tilauscope_roast_plan","Target ROR Maillard")+f" (°{self.mode}/min)", plan_data.get("Target ROR Maillard")),
            (QApplication.translate("tilauscope_roast_plan","Target ROR Dev")+" ("+QApplication.translate("tilauscope_roast_plan","Average")+f" °{self.mode}/min)", plan_data.get("Target ROR Dev (Avg)")),
            (QApplication.translate("tilauscope_roast_plan","Target ROR at Drop")+f" (°{self.mode}/min)", plan_data.get("Target ROR at Drop")),
        ]

        self.set_font('helvetica', '', 10)
        for label, value in ratio_data:
            self.cell(80, _row_h, label + ':', border=0)
            self.cell(0, _row_h, str(value), new_x=XPos.LMARGIN, new_y=YPos.NEXT, border=0)

        # 4. Machine settings AT PHASE ENTRY — see _entry_settings.
        self.ln(3)
        self.set_fill_color(220, 220, 220)
        self.set_font('helvetica', 'B', 12)
        self.cell(0, 7, QApplication.translate("tilauscope_roast_plan",
            '4. Machine Settings at Phase Entry (what to be on when you cross the milestone)'),
            new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True)
        self.ln(1)
        self.set_font('helvetica', 'I', 8.5)
        self.multi_cell(0, 4, QApplication.translate("tilauscope_roast_plan",
            "The value the machine must read as each phase begins. Between these points the "
            "plan steps the levers: the full sequence is in section 5."), border=0)
        self.ln(1)

        _entry_rows = self._entry_settings(plan_data)
        col_widths = [42, 38, 38, 42]

        # Table Header
        self.set_fill_color(220, 220, 220)
        self.set_font('helvetica', 'B', 10)
        self.cell(col_widths[0], 7, QApplication.translate("tilauscope_roast_plan","Control"), 1, align='C', fill=True)
        self.cell(col_widths[1], 7, QApplication.translate("tilauscope_roast_plan","At CHARGE"), 1, align='C', fill=True)
        self.cell(col_widths[2], 7, QApplication.translate("Button","DRY END"), 1, align='C', fill=True)
        self.cell(col_widths[3], 7, QApplication.translate("Button","FC START"), 1, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C', fill=True)

        # Table Rows
        self.set_font('helvetica', '', 10)
        for label, values in _entry_rows:
            v = (list(values) + ['N/A', 'N/A', 'N/A'])[:3]
            self.cell(col_widths[0], _row_h, label, 1)
            self.cell(col_widths[1], _row_h, v[0], 1, align='C')
            self.cell(col_widths[2], _row_h, v[1], 1, align='C')
            self.cell(col_widths[3], _row_h, v[2], 1, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')

        # AirWave mode is a regime for the phase, not a value crossed at an
        # instant, so it keeps its per-phase reading and says so.
        _awm = str(plan_data.get("AirWave Mode (Dry|Mai|Dev)", "")).strip()
        if _awm:
            _m = (_awm.split(' | ') + ['N/A', 'N/A', 'N/A'])[:3]
            self.cell(col_widths[0], _row_h,
                      QApplication.translate("tilauscope_roast_plan","AirWave Mode")
                      + " " + QApplication.translate("tilauscope_roast_plan","(per phase)"), 1)
            self.cell(col_widths[1], _row_h, _m[0], 1, align='C')
            self.cell(col_widths[2], _row_h, _m[1], 1, align='C')
            self.cell(col_widths[3], _row_h, _m[2], 1, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')

        self.ln(3)
        self.set_font('helvetica', 'I', 9)
        self.multi_cell(0, 4,
                        QApplication.translate("tilauscope_roast_plan","Note: The plan is generated for a Target Agtron profile of ")+
                        f"{plan_data.get('Target Agtron', 'N/A')} (Resulting DTR: {plan_data.get('Target DTR', 'N/A')}). "+
                        QApplication.translate("tilauscope_roast_plan","All temperatures are in BT (Bean Temperature) and times in Minutes:Seconds."),
                        border=0)

        # 5. Control ramps — the section 4 table gives one value per phase, which
        # is unreadable as a gesture sequence: the heater ramp alone is up to a
        # dozen "x% @ y°" pairs in a run-on line. Drawn over time, the same data
        # says at a glance when to move, by how much, and in which direction.
        # Its own page: it is what the operator keeps in front of them.
        try:
            # Ask for the trajectories BEFORE opening the page: a plan with
            # nothing to draw must not leave a titled blank page behind.
            _h_traj, _a_traj, _ = self._control_trajectories(plan_data)
        except Exception as e:
            _logd.error(f"error building control trajectories : {e}")
            _h_traj, _a_traj = [], []

        if _h_traj or _a_traj:
            try:
                self.add_page()
                self.set_fill_color(220, 220, 220)
                self.set_font('helvetica', 'B', 12)
                self.cell(0, 7, QApplication.translate(
                    "tilauscope_roast_plan", '5. Control Ramps (Heater & Airflow)'),
                    new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True)
                self.ln(4)
                self.set_font('helvetica', 'I', 9)
                self.multi_cell(0, 4, QApplication.translate(
                    "tilauscope_roast_plan",
                    "Each level is held until the next step: the plan asks for one move at a time, "
                    "then time to read its effect. Steps are anchored on bean temperature and shown "
                    "here at the time the planned curve reaches them."),
                    border=0)
                self.ln(4)
                if self.draw_control_ramp_graph(
                        plan_data, x_pos=self.get_x() + 12, y_pos=self.get_y(),
                        width=160, height=62):
                    self.set_y(self.get_y() + 82)
                self._draw_step_sequence(plan_data)
                self._draw_plan_recap(plan_data)
            except Exception as e:
                _logd.error(f"error drawing control ramp graph : {e}")

        # 6. Historical Feedback (Notes and Actions)
        notes = plan_data.get("notes", [])
        actions = plan_data.get("actions", [])

        if notes is not None and len(notes)>0:
            self.add_page(same=True)
            try:
                self.set_fill_color(220, 220, 220)
                self.set_font('helvetica', 'B', 12)
                self.cell(0, 7, QApplication.translate("tilauscope_roast_plan",'6. Historical Feedback & Actions'), new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True)
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

            t_marks = [t0, t1, t2]

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

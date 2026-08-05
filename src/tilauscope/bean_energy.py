"""
Demande énergétique du grain vert — plancher de brûleur en Maillard.

Spec de référence : `wiki/BeanEnergy-MaillardFloor-Spec.md`.

Pourquoi ce module existe
-------------------------
En Maillard les réactions sont ENDOTHERMIQUES : elles consomment l'énergie qu'on
leur donne. Baisser le brûleur n'y décélère pas doucement, ça AFFAME la réaction.
La température continue de monter (masse thermique du tambour), le RoR reste beau,
et la chimie a décroché — c'est le roast *baked*.

Conséquence : un RoR lisse et décroissant ne prouve PAS que le roast est nourri.
Le contrôle ne peut donc pas porter sur la courbe, il porte sur la trajectoire des
réglages, et il lui faut une référence : la quantité d'énergie que CE grain-là
réclame pour ne pas décrocher. C'est le plancher que ce module calcule.

Le plancher n'est ni un nombre ni un palier : c'est une courbe, définie par deux
grandeurs issues du grain — un NIVEAU (demande énergétique) et une FRACTION DE
RELÂCHEMENT (le moment du Maillard où l'exothermie prend le relais et où le
plancher a le droit de céder).

Contrat
-------
Fonctions pures. Aucun Qt, aucune I/O, aucun accès disque, aucune chaîne
utilisateur — les messages destinés à l'opérateur sont construits par l'appelant,
qui seul a accès au traducteur. Ce module ne produit que des données et des logs.
"""

from __future__ import annotations

import logging
import unicodedata
from dataclasses import dataclass, field

_log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  TABLES — éditer ici, jamais dans la logique de plan
# ══════════════════════════════════════════════════════════════════════════════

# Base par process, en % de brûleur Skywalker chargé, et fraction du Maillard à
# laquelle le plancher a le droit de commencer à descendre.
#
# Le levier chimique dominant : le SACCHAROSE EST UN SUCRE NON RÉDUCTEUR. Il doit
# être inverti en glucose et fructose avant de pouvoir entrer en réaction de
# Maillard. Cette étape supplémentaire est ce qui sépare un lavé d'un natural.
PROCESS_BASE: dict[str, tuple[float, float]] = {
    # lavé : saccharose intact à invertir, barrière d'activation haute,
    # brunissement interne, demande soutenue longtemps, FC net
    "washed":    (62.0, 0.75),
    # honey : mucilage partiel, sucres partiellement disponibles
    "honey":     (58.0, 0.65),
    # natural : la fermentation sur le fruit a pré-dégradé les sucres en sucres
    # RÉDUCTEURS déjà disponibles en surface — réaction plus auto-entretenue
    "natural":   (55.0, 0.60),
    # anaérobie : alcools, acides organiques, précurseurs volatils — le plus
    # réactif et le plus fragile de la série
    "fermented": (53.0, 0.55),
    # décaf : structure pré-gélatinisée par le procédé, acides chlorogéniques et
    # sucres partiellement lessivés — moins de matière à faire réagir, FC sourd
    "decaf":     (50.0, 0.55),
}

_PROCESS_DEFAULT = "washed"

# Ordre de test significatif : le décaf en premier (le plus spécifique, peut
# cohabiter avec un mot de process — « decaf washed »), puis les fermentations,
# puis honey, puis natural, le lavé en repli.
_PROCESS_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("decaf",     ("decaf", "decaffeinated", "decafeine", "swiss water")),
    ("fermented", ("anaerobic", "anaerobie", "fermentation", "fermented",
                   "fermente", "carbonic", "maceration", "yeast", "levure",
                   "koji", "lactic")),
    ("honey",     ("honey", "miel", "pulped natural", "semi washed",
                   "semi-washed", "wet hulled", "giling")),
    ("natural",   ("natural", "nature", "dry process", "dry-process", "sec")),
    ("washed",    ("washed", "lave", "wet process", "fully washed")),
)

# Variété — ce que la densité affichée ne capte pas : teneur en saccharose et
# épaisseur de paroi cellulaire se décorrèlent d'elle.
# Valeurs : (delta niveau, delta fraction de relâchement).
#
# ⚠ Ordre significatif : le premier mot-clé trouvé gagne. Les libellés les plus
# spécifiques doivent précéder les plus génériques (« catuai » avant « catu- »).
VARIETY_KEYWORDS: tuple[tuple[tuple[str, ...], float, float], ...] = (
    # Introgression Robusta via le Timor Hybrid : saccharose plus bas, acides
    # chlorogéniques plus hauts, paroi épaisse → s'auto-entretient TARD
    (("sarchimor", "catimor", "castillo", "obata", "kartika", "colombia var",
      "timor", "ruiru"), +2.0, +0.08),
    # Parois très épaisses — la demande la plus haute de la table
    (("sl28", "sl 28", "sl34", "sl 34", "sl-28", "sl-34"), +3.0, +0.10),
    # Très gros calibre : rapport surface/volume défavorable, le cœur traîne
    (("pacamara", "maragogype", "maragogipe"), +2.0, +0.05),
    # F1 Sarchimor x Rume Sudan — introgression partielle, gros grain
    (("centroamericano", "h1", "marsellesa", "starmaya"), +1.0, +0.05),
    # Paroi fine, densité faible pour son altitude — tippe si on le pousse
    (("gesha", "geisha"), -3.0, -0.08),
    # Petit calibre : la chaleur atteint le cœur vite malgré une densité correcte
    (("jarc", "74110", "74112", "74158", "kurume", "heirloom", "landrace",
      "wolisho", "dega"), -2.0, -0.05),
    # Mundo Novo x Caturra, légèrement plus dense que la référence
    (("catuai",), +1.0, 0.0),
    # Référence — lignée riche en saccharose (7,5-9 % sur sec)
    (("bourbon", "caturra", "typica", "java", "ab3", "mundo novo", "pacas",
      "villa sarchi", "sl14", "batian"), 0.0, 0.0),
)

# Terroir — ne porte QUE ce que la densité ne capte pas : structure et
# composition à densité égale. Reste donc petit (voir CAP_VARIETY_TERROIR).
TERROIR_KEYWORDS: tuple[tuple[tuple[str, ...], float], ...] = (
    (("kenya",),                          +2.0),  # parois épaisses, forte demande
    (("colombia", "colombie"),            +1.0),  # lignée introgressée dominante
    (("india", "inde", "vietnam"),        +1.0),
    (("ethiopia", "ethiopie"),            -1.0),  # petit calibre, pénétration rapide
    (("brazil", "bresil", "brasil"),      -2.0),  # basse altitude, structure lâche
    (("indonesia", "indonesie", "sumatra", "java island", "sulawesi"), -2.0),
    # giling basah : le décorticage humide ouvre la structure cellulaire
    # ── Référence explicite (delta 0) ────────────────────────────────────────
    # Ces origines NE SONT PAS des oublis : à densité égale elles sont la
    # structure de référence sur laquelle les bases de process sont posées.
    # Les lister les fait reconnaître au lieu d'être signalées comme inconnues —
    # « non listé » doit rester le signal d'un libellé qu'on n'a pas su lire.
    (("guatemala", "costa rica", "nicaragua", "honduras", "el salvador",
      "salvador", "panama", "mexico", "mexique", "peru", "perou", "bolivia",
      "bolivie", "rwanda", "burundi", "tanzania", "tanzanie", "uganda",
      "ouganda", "papua", "papouasie", "timor"), 0.0),
)

# Constantes physiques
DENSITY_REF_G_L: float = 700.0
DENSITY_PTS_PER_50: float = 2.0

HUMIDITY_HIGH_PCT: float = 11.5   # au-dessus : l'eau reste un puits de chaleur
HUMIDITY_LOW_PCT: float = 9.5     # en dessous : vieux crop, tout s'accélère
HUMIDITY_PTS_PER_PCT: float = 2.0

# Activité de l'eau — ne change PAS la demande totale, elle change OÙ elle se paie.
# L'humidité dit COMBIEN d'eau ; l'aw dit À QUEL POINT elle est liée. Eau libre :
# payée au séchage. Eau liée (aw basse) : continue de sortir pendant le Maillard,
# où elle reste un puits de chaleur et retarde l'auto-entretien.
AW_BOUND_BELOW: float = 0.50
AW_FREE_ABOVE: float = 0.60
AW_BOUND_LEVEL: float = +2.0
AW_BOUND_RELEASE: float = +0.05
AW_FREE_LEVEL: float = -1.0

# Ambiance — significative parce que la machine est PULL-TYPE : l'air d'admission
# est celui de la pièce et participe directement à l'énergie convective livrée.
AMBIENT_TEMP_STEPS: tuple[tuple[float, float], ...] = (
    (15.0, +2.0),   # < 15 °C
    (20.0, +1.0),   # 15-20 °C
    (25.0,  0.0),   # 20-25 °C
)
AMBIENT_TEMP_ABOVE: float = -1.0       # > 25 °C
AMBIENT_HUMIDITY_HIGH_PCT: float = 70.0
AMBIENT_HUMIDITY_LEVEL: float = +1.0

# Plafonds et bornes
CAP_VARIETY_TERROIR: float = 4.0
CAP_AMBIENT: float = 2.0
CAP_TOTAL_MODULATION: float = 6.0
# Plancher absolu : sous ~50 % le banc mesure +0,03 °C/min de RoR par % de
# brûleur (contre +1,17 depuis >= 75 %). L'organe n'a plus d'autorité, on ne
# pilote plus rien — c'est la falaise d'autorité, pas une préférence de style.
FLOOR_ABSOLUTE_PCT: float = 50.0
RELEASE_MIN: float = 0.50
RELEASE_MAX: float = 0.85
# Descente du plancher après le relâchement, jusqu'au point pre-FC.
RELEASE_DROP_PCT: float = 5.0

# Fenêtres de plausibilité. 0.0 est la sentinelle « non mesuré » du codebase :
# absente, pas implausible — elle ne doit produire aucun avertissement.
_WINDOW_DENSITY: tuple[float, float] = (250.0, 1000.0)
_WINDOW_BEAN_HUMIDITY: tuple[float, float] = (5.0, 20.0)
_WINDOW_AW: tuple[float, float] = (0.20, 1.00)
_WINDOW_AMBIENT_TEMP: tuple[float, float] = (-10.0, 60.0)
_WINDOW_AMBIENT_HUMIDITY: tuple[float, float] = (0.0, 100.0)


# ══════════════════════════════════════════════════════════════════════════════
#  TYPES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class BeanProps:
    """Propriétés d'un grain vert, en valeurs simples (pas de GreenBean ici :
    le module doit rester testable sans le reste de l'application)."""
    process: str = ""
    varieties: str = ""
    country: str = ""
    density_g_l: float = 0.0
    humidity_pct: float = 0.0
    water_activity: float = 0.0


@dataclass(frozen=True)
class Ambient:
    temp_c: float = 0.0
    humidity_pct: float = 0.0


@dataclass(frozen=True)
class FloorProfile:
    """Le plancher de brûleur en Maillard.

    `level_pct` est tenu à plat de la fin du séchage jusqu'à `release_fraction`
    du Maillard, puis descend linéairement de `RELEASE_DROP_PCT` jusqu'au point
    pre-FC. `unresolved` liste les libellés qu'aucune table n'a reconnus — un
    grain non reconnu doit être VISIBLE, jamais silencieusement traité comme un
    Bourbon."""
    level_pct: float
    release_fraction: float
    unresolved: tuple[str, ...] = ()
    contributions: dict[str, float] = field(default_factory=dict)

    def at(self, maillard_fraction: float) -> float:
        """Valeur du plancher à une fraction du Maillard écoulée [0, 1]."""
        u = _clamp(float(maillard_fraction), 0.0, 1.0)
        if u <= self.release_fraction:
            return self.level_pct
        span = 1.0 - self.release_fraction
        if span <= 0.0:
            return max(FLOOR_ABSOLUTE_PCT, self.level_pct - RELEASE_DROP_PCT)
        progress = (u - self.release_fraction) / span
        return max(FLOOR_ABSOLUTE_PCT,
                   self.level_pct - RELEASE_DROP_PCT * progress)


# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _clamp(value: float, lo: float, hi: float) -> float:
    return lo if value < lo else (hi if value > hi else value)


def normalise(text: str | None) -> str:
    """Chaîne comparable : minuscules, sans accents, ponctuation en espaces.

    Les libellés du grain vert sont saisis à la main — « Geisha (Panama) "Gesha" »,
    « Obata (Red) Sarchimor », « Natural / Dry Process »."""
    if not text:
        return ""
    folded = unicodedata.normalize("NFKD", str(text))
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    out = [c if (c.isalnum() or c.isspace()) else " " for c in folded.lower()]
    return " ".join("".join(out).split())


def _plausible(value: float | None, window: tuple[float, float],
               label: str) -> float | None:
    """Filtre une entrée. 0.0 = « non mesuré » : silencieux. Hors fenêtre :
    ignoré ET tracé, parce qu'une donnée aberrante doit se voir."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v == 0.0:
        return None
    lo, hi = window
    if not (lo <= v <= hi):
        _log.warning("BeanEnergy: %s %.2f out of plausible range [%g, %g] "
                     "— ignored", label, v, lo, hi)
        return None
    return v


def match_process(process: str | None) -> str | None:
    """Clé de `PROCESS_BASE`, ou None si rien ne matche."""
    text = normalise(process)
    if not text:
        return None
    for key, words in _PROCESS_KEYWORDS:
        if any(w in text for w in words):
            return key
    return None


def match_variety(varieties: str | None) -> tuple[float, float] | None:
    """(delta niveau, delta relâchement), ou None si rien ne matche."""
    text = normalise(varieties)
    if not text:
        return None
    for words, d_level, d_release in VARIETY_KEYWORDS:
        if any(w in text for w in words):
            return (d_level, d_release)
    return None


def match_terroir(country: str | None) -> float | None:
    """Delta niveau, ou None si rien ne matche (le repli vaut 0, pas None :
    la distinction sert à savoir si le libellé a été reconnu)."""
    text = normalise(country)
    if not text:
        return None
    for words, d_level in TERROIR_KEYWORDS:
        if any(w in text for w in words):
            return d_level
    return None


def _ambient_level(ambient: Ambient | None) -> float:
    if ambient is None:
        return 0.0
    total = 0.0
    t = _plausible(ambient.temp_c, _WINDOW_AMBIENT_TEMP, "ambient temperature")
    if t is not None:
        for threshold, pts in AMBIENT_TEMP_STEPS:
            if t < threshold:
                total += pts
                break
        else:
            total += AMBIENT_TEMP_ABOVE
    h = _plausible(ambient.humidity_pct, _WINDOW_AMBIENT_HUMIDITY,
                   "ambient humidity")
    if h is not None and h > AMBIENT_HUMIDITY_HIGH_PCT:
        total += AMBIENT_HUMIDITY_LEVEL
    return _clamp(total, -CAP_AMBIENT, CAP_AMBIENT)


# Ces trois helpers rendent None pour « non mesuré » et 0.0 pour « mesuré, mais
# dans la bande neutre ». La distinction n'est pas cosmétique : elle est ce qui
# permet à un mélange d'ÉCARTER un composant d'un terme précis au lieu de le
# compter à la valeur de référence, ce qui serait une correction silencieuse.

def _density_level(density: float | None) -> float | None:
    d = _plausible(density, _WINDOW_DENSITY, "bean density")
    if d is None:
        return None
    return DENSITY_PTS_PER_50 * (d - DENSITY_REF_G_L) / 50.0


def _humidity_level(humidity: float | None) -> float | None:
    h = _plausible(humidity, _WINDOW_BEAN_HUMIDITY, "bean humidity")
    if h is None:
        return None
    if h > HUMIDITY_HIGH_PCT:
        return HUMIDITY_PTS_PER_PCT * (h - HUMIDITY_HIGH_PCT)
    if h < HUMIDITY_LOW_PCT:
        return -HUMIDITY_PTS_PER_PCT * (HUMIDITY_LOW_PCT - h)
    return 0.0


def _aw_deltas(water_activity: float | None) -> tuple[float, float] | None:
    aw = _plausible(water_activity, _WINDOW_AW, "water activity")
    if aw is None:
        return None
    if aw < AW_BOUND_BELOW:
        return (AW_BOUND_LEVEL, AW_BOUND_RELEASE)
    if aw > AW_FREE_ABOVE:
        return (AW_FREE_LEVEL, 0.0)
    return (0.0, 0.0)


# ══════════════════════════════════════════════════════════════════════════════
#  API
# ══════════════════════════════════════════════════════════════════════════════

def maillard_floor(bean: BeanProps,
                   ambient: Ambient | None = None) -> FloorProfile:
    """Plancher de brûleur en Maillard pour un grain simple."""
    unresolved: list[str] = []

    process_key = match_process(bean.process)
    if process_key is None:
        if normalise(bean.process):
            unresolved.append(f"process:{bean.process}")
        process_key = _PROCESS_DEFAULT
        _log.info("BeanEnergy: process %r unrecognised — falling back to %s",
                  bean.process, _PROCESS_DEFAULT)
    base_level, base_release = PROCESS_BASE[process_key]

    variety = match_variety(bean.varieties)
    if variety is None:
        if normalise(bean.varieties):
            unresolved.append(f"variety:{bean.varieties}")
            _log.info("BeanEnergy: variety %r unrecognised — no correction "
                      "applied", bean.varieties)
        variety = (0.0, 0.0)
    d_var_level, d_release = variety

    terroir = match_terroir(bean.country)
    if terroir is None:
        if normalise(bean.country):
            unresolved.append(f"country:{bean.country}")
        terroir = 0.0

    # Variété et terroir se recouvrent en partie (une variété introgressée est
    # souvent colombienne) — plafonner leur somme est ce qui empêche le double
    # comptage de partir en vrille.
    var_terroir = _clamp(d_var_level + terroir,
                         -CAP_VARIETY_TERROIR, CAP_VARIETY_TERROIR)

    d_density = _density_level(bean.density_g_l)
    d_humidity = _humidity_level(bean.humidity_pct)
    aw = _aw_deltas(bean.water_activity)
    d_aw_level, d_aw_release = aw if aw is not None else (0.0, 0.0)
    d_ambient = _ambient_level(ambient)

    modulation = _clamp(
        var_terroir + (d_density or 0.0) + (d_humidity or 0.0)
        + d_aw_level + d_ambient,
        -CAP_TOTAL_MODULATION, CAP_TOTAL_MODULATION)

    level = max(FLOOR_ABSOLUTE_PCT, base_level + modulation)
    release = _clamp(base_release + d_release + d_aw_release,
                     RELEASE_MIN, RELEASE_MAX)

    # Un terme non mesuré est ABSENT du dict, pas à zéro — c'est ce qui permet
    # à maillard_floor_blend de l'écarter au lieu de le moyenner.
    contributions: dict[str, float] = {
        "process_base": base_level,
        "variety": d_var_level,
        "terroir": terroir,
        "variety_terroir_capped": var_terroir,
        "ambient": d_ambient,
        "modulation_applied": round(modulation, 2),
    }
    if d_density is not None:
        contributions["density"] = round(d_density, 2)
    if d_humidity is not None:
        contributions["bean_humidity"] = round(d_humidity, 2)
    if aw is not None:
        contributions["water_activity"] = d_aw_level

    return FloorProfile(
        level_pct=round(level, 1),
        release_fraction=round(release, 3),
        unresolved=tuple(unresolved),
        contributions=contributions,
    )


def maillard_floor_blend(components: "list[tuple[BeanProps, float]]",
                         ambient: Ambient | None = None) -> FloorProfile:
    """Plancher d'un mélange.

    ⚠️ ÉCRITE MAIS PAS APPELÉE par le plan model, par décision (2026-08-05).
    `bean2_name` / `bean3_name` sont des VARIÉTÉS du même vocabulaire contrôlé que
    le grain 1 (`coffee_bean_types['Arabica']`, la liste qui alimente aussi son
    combo variété) : `match_variety` les lirait sans rien résoudre. Ce qui manque
    n'est pas le libellé, c'est le RESTE — process, pays, densité, humidité, aw
    sont mesurés sur la fiche entière, pas par composant. Seul le terme variété
    serait donc pondérable, et il plafonne à CAP_VARIETY_TERROIR sur une
    modulation totale de CAP_TOTAL_MODULATION.

    En pratique les grains 2 et 3 viennent de la même coopérative ou ferme que le
    grain 1 : le reste des propriétés est bien partagé, et le plancher du grain 1
    est une approximation acceptable. À rouvrir si les fiches de mélange gagnent
    des propriétés par composant.

    Pondération par les ratios. Un composant dont la donnée manque est ÉCARTÉ du
    calcul et les ratios sont RENORMALISÉS sur les composants renseignés — terme
    par terme. On n'inclut jamais un composant non renseigné à la valeur de
    référence : ce serait une correction silencieuse, pas une abstention.

    `components` : [(props, ratio)]. Ratios absents ou tous nuls → repli sur le
    premier composant seul."""
    usable = [(b, float(r)) for b, r in components if b is not None]
    if not usable:
        return maillard_floor(BeanProps(), ambient)

    total_ratio = sum(r for _, r in usable if r > 0.0)
    if total_ratio <= 0.0:
        # Pas de ratios exploitables : repli sur le grain 1, comme arbitré.
        return maillard_floor(usable[0][0], ambient)

    profiles = [(maillard_floor(b, ambient=None), r)
                for b, r in usable if r > 0.0]

    def _weighted(key: str) -> float:
        """Moyenne pondérée d'un terme sur les seuls composants qui l'ont
        renseigné, ratios renormalisés sur eux."""
        pairs = [(p.contributions.get(key, 0.0), r) for p, r in profiles
                 if key in p.contributions]
        weight = sum(r for _, r in pairs)
        if weight <= 0.0:
            return 0.0
        return sum(v * r for v, r in pairs) / weight

    base_level = _weighted("process_base")
    var_terroir = _clamp(_weighted("variety") + _weighted("terroir"),
                         -CAP_VARIETY_TERROIR, CAP_VARIETY_TERROIR)
    modulation = _clamp(
        var_terroir + _weighted("density") + _weighted("bean_humidity")
        + _weighted("water_activity") + _ambient_level(ambient),
        -CAP_TOTAL_MODULATION, CAP_TOTAL_MODULATION)

    weight = sum(r for _, r in profiles)
    release = sum(p.release_fraction * r for p, r in profiles) / weight

    unresolved: list[str] = []
    for p, _ in profiles:
        unresolved.extend(p.unresolved)

    return FloorProfile(
        level_pct=round(max(FLOOR_ABSOLUTE_PCT, base_level + modulation), 1),
        release_fraction=round(_clamp(release, RELEASE_MIN, RELEASE_MAX), 3),
        unresolved=tuple(unresolved),
        contributions={
            "process_base": round(base_level, 2),
            "variety_terroir_capped": round(var_terroir, 2),
            "modulation_applied": round(modulation, 2),
            "components": float(len(profiles)),
        },
    )

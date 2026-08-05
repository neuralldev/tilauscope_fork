"""Demande énergétique du grain — plancher de Maillard.

Suite du module `tilauscope.bean_energy`. Il est volontairement pur (aucun Qt,
aucune I/O), donc il se teste sans générer un plan ni ouvrir de fichier.

Spec : `wiki/BeanEnergy-MaillardFloor-Spec.md`.
"""

from __future__ import annotations

import pytest

from tilauscope.bean_energy import (
    Ambient,
    BeanProps,
    FLOOR_ABSOLUTE_PCT,
    PROCESS_BASE,
    RELEASE_MAX,
    RELEASE_MIN,
    maillard_floor,
    maillard_floor_blend,
    match_process,
    match_terroir,
    match_variety,
    normalise,
)


# ── Normalisation des libellés saisis à la main ──────────────────────────────

@pytest.mark.parametrize('raw, expected', [
    ('Geisha (Panama) “Gesha”', 'geisha panama gesha'),
    ('Obata (Red) Sarchimor',   'obata red sarchimor'),
    ('Natural / Dry Process',   'natural dry process'),
    ('Éthiopie',                'ethiopie'),
    (None,                      ''),
])
def test_normalise_flattens_case_accents_and_punctuation(raw, expected):
    assert normalise(raw) == expected


# ── Process ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('raw, key', [
    ('Washed / Wet Process',      'washed'),
    ('Natural / Dry Process',     'natural'),
    ('Anaerobic Fermentation',    'fermented'),
    ('Honey',                     'honey'),
    ('Wet Hulled',                'honey'),
    ('Carbonic Maceration',       'fermented'),
])
def test_process_keywords_resolve(raw, key):
    assert match_process(raw) == key


def test_decaf_wins_over_a_coexisting_process_word():
    # « decaf washed » doit tomber en décaf : le libellé le plus spécifique gagne.
    assert match_process('Decaf Washed') == 'decaf'


def test_anaerobic_no_longer_falls_through_to_washed():
    # Le défaut qui envoyait les anaérobies sur la bande lavée.
    assert match_process('Anaerobic Fermentation') != 'washed'


def test_unknown_process_falls_back_to_washed_and_is_flagged():
    p = maillard_floor(BeanProps(process='Cryogenic Something'))
    assert p.contributions['process_base'] == PROCESS_BASE['washed'][0]
    assert any(u.startswith('process:') for u in p.unresolved)


# ── Variété ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('raw, d_level', [
    ('Bourbon',                   0.0),
    ('Caturra',                   0.0),
    ('Typica',                    0.0),
    ('AB3 Java',                  0.0),
    ('Catuai',                   +1.0),
    ('Centroamericano H1',       +1.0),
    ('Obata (Red) Sarchimor',    +2.0),
    ('Kartika 1',                +2.0),
    ('SL28',                     +3.0),
    ('Pacamara',                 +2.0),
    ('JARC 74110 Heirloom',      -2.0),
    ('Kurume',                   -2.0),
    ('Geisha (Panama) “Gesha”',  -3.0),
])
def test_variety_levels(raw, d_level):
    assert match_variety(raw)[0] == d_level


def test_catuai_and_caturra_are_not_confused():
    assert match_variety('Catuai')[0] == +1.0
    assert match_variety('Caturra')[0] == 0.0


def test_robusta_introgression_releases_latest():
    # Saccharose plus bas + paroi épaisse → s'auto-entretient tard.
    assert match_variety('Obata Sarchimor')[1] > match_variety('Bourbon')[1]
    # Gesha : paroi fine, auto-entretien précoce.
    assert match_variety('Gesha')[1] < match_variety('Bourbon')[1]


def test_unknown_variety_is_visible_not_silently_reference():
    p = maillard_floor(BeanProps(process='Washed', varieties='Zorglub'))
    assert p.contributions['variety'] == 0.0
    assert any(u.startswith('variety:') for u in p.unresolved)


# ── Terroir ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('raw, d_level', [
    ('Kenya',      +2.0),
    ('Colombia',   +1.0),
    ('Guatemala',    0.0),   # référence explicite, pas un oubli
    ('Costa Rica',   0.0),
    ('Nicaragua',    0.0),
    ('Ethiopia',   -1.0),
    ('Brazil',     -2.0),
    ('Indonesia',  -2.0),
])
def test_terroir_levels(raw, d_level):
    assert match_terroir(raw) == d_level


def test_an_unread_country_stays_unresolved():
    """« Non listé » doit rester le signal d'un libellé qu'on n'a pas su lire —
    d'où les origines de référence listées explicitement à 0."""
    assert match_terroir('Zorglubie') is None
    p = maillard_floor(BeanProps(process='Washed', country='Zorglubie'))
    assert any(u.startswith('country:') for u in p.unresolved)
    assert not maillard_floor(BeanProps(process='Washed',
                                        country='Guatemala')).unresolved


# ── Ordre chimique attendu ───────────────────────────────────────────────────

def test_process_bases_follow_the_sucrose_argument():
    """Le saccharose est non réducteur : il doit être inverti avant d'entrer en
    Maillard. Un lavé porte donc la demande la plus haute, un fermenté la plus
    basse — et le décaf, pré-dégradé par son procédé, plus basse encore."""
    lv = {k: v[0] for k, v in PROCESS_BASE.items()}
    assert lv['washed'] > lv['honey'] > lv['natural'] > lv['fermented'] > lv['decaf']


def test_release_fraction_follows_the_same_order():
    rel = {k: v[1] for k, v in PROCESS_BASE.items()}
    assert rel['washed'] > rel['honey'] > rel['natural'] >= rel['fermented']


# ── Constantes physiques ─────────────────────────────────────────────────────

def test_denser_beans_demand_more():
    dense = maillard_floor(BeanProps(process='Washed', density_g_l=800.0))
    light = maillard_floor(BeanProps(process='Washed', density_g_l=600.0))
    assert dense.level_pct > light.level_pct


def test_bound_water_raises_the_floor_and_delays_release():
    """L'aw ne change pas la demande totale, elle change où elle se paie :
    l'eau liée continue de sortir pendant le Maillard."""
    bound = maillard_floor(BeanProps(process='Washed', water_activity=0.44))
    free = maillard_floor(BeanProps(process='Washed', water_activity=0.65))
    assert bound.level_pct > free.level_pct
    assert bound.release_fraction > free.release_fraction


def test_humidity_neutral_band_contributes_nothing():
    p = maillard_floor(BeanProps(process='Washed', humidity_pct=10.5))
    assert p.contributions['bean_humidity'] == 0.0


def test_cold_room_costs_energy_on_a_pull_type_machine():
    cold = maillard_floor(BeanProps(process='Washed'), Ambient(temp_c=12.0))
    warm = maillard_floor(BeanProps(process='Washed'), Ambient(temp_c=28.0))
    assert cold.level_pct > warm.level_pct


# ── Plausibilité ─────────────────────────────────────────────────────────────

def test_absurd_ambient_is_ignored_not_saturated():
    """Le corpus porte des ambiantes à 526 °C et 555 °C. Elles poussaient la
    modulation au plafond sans que rien ne le signale."""
    absurd = maillard_floor(BeanProps(process='Washed'), Ambient(temp_c=526.4))
    none = maillard_floor(BeanProps(process='Washed'), Ambient(temp_c=0.0))
    assert absurd.level_pct == none.level_pct


def test_zero_is_the_not_measured_sentinel_and_stays_silent(caplog):
    with caplog.at_level('WARNING'):
        maillard_floor(BeanProps(process='Washed', density_g_l=0.0,
                                 humidity_pct=0.0, water_activity=0.0))
    assert not [r for r in caplog.records if 'out of plausible' in r.message]


def test_out_of_window_value_is_ignored_and_logged(caplog):
    with caplog.at_level('WARNING'):
        maillard_floor(BeanProps(process='Washed', density_g_l=2500.0))
    assert any('out of plausible' in r.getMessage() for r in caplog.records)


# ── Bornes ───────────────────────────────────────────────────────────────────

def test_floor_never_goes_under_the_authority_cliff():
    """Sous ~50 % le brûleur rend +0,03 °C/min par % : il n'est plus un levier."""
    p = maillard_floor(
        BeanProps(process='Decaf', varieties='Gesha', country='Brazil',
                  density_g_l=400.0, humidity_pct=8.0),
        Ambient(temp_c=30.0))
    assert p.level_pct >= FLOOR_ABSOLUTE_PCT


def test_total_modulation_is_capped():
    extreme = maillard_floor(
        BeanProps(process='Washed', varieties='SL28', country='Kenya',
                  density_g_l=1000.0, humidity_pct=19.0, water_activity=0.30),
        Ambient(temp_c=-5.0, humidity_pct=95.0))
    assert extreme.level_pct <= PROCESS_BASE['washed'][0] + 6.0


def test_release_fraction_stays_inside_its_window():
    for bean in (BeanProps(process='Washed', varieties='SL28',
                           water_activity=0.40),
                 BeanProps(process='Fermented', varieties='Gesha')):
        p = maillard_floor(bean)
        assert RELEASE_MIN <= p.release_fraction <= RELEASE_MAX


# ── Forme de la courbe ───────────────────────────────────────────────────────

def test_floor_is_flat_then_descends():
    p = maillard_floor(BeanProps(process='Washed'))
    r = p.release_fraction
    assert p.at(0.0) == p.level_pct
    assert p.at(r) == p.level_pct              # tenu jusqu'au relâchement
    assert p.at(1.0) < p.level_pct             # puis il cède
    assert p.at(1.0) >= FLOOR_ABSOLUTE_PCT


def test_floor_descent_is_monotone():
    p = maillard_floor(BeanProps(process='Natural'))
    samples = [p.at(u / 20.0) for u in range(21)]
    assert all(b <= a + 1e-9 for a, b in zip(samples, samples[1:], strict=False))


# ── Mélanges ─────────────────────────────────────────────────────────────────

def test_blend_weights_by_ratio():
    washed = BeanProps(process='Washed')
    fermented = BeanProps(process='Anaerobic Fermentation')
    mostly_washed = maillard_floor_blend([(washed, 0.9), (fermented, 0.1)])
    mostly_ferm = maillard_floor_blend([(washed, 0.1), (fermented, 0.9)])
    assert mostly_washed.level_pct > mostly_ferm.level_pct


def test_blend_without_ratios_falls_back_to_the_first_bean():
    washed = BeanProps(process='Washed')
    fermented = BeanProps(process='Anaerobic Fermentation')
    blend = maillard_floor_blend([(washed, 0.0), (fermented, 0.0)])
    assert blend.level_pct == maillard_floor(washed).level_pct


def test_a_component_without_data_is_dropped_not_averaged_as_reference():
    """« Tant pis, il fallait les renseigner » : abstention, pas correction
    silencieuse. Le composant sans densité ne doit pas tirer la moyenne."""
    dense = BeanProps(process='Washed', density_g_l=850.0)
    unknown = BeanProps(process='Washed')          # densité non renseignée
    blend = maillard_floor_blend([(dense, 0.5), (unknown, 0.5)])
    assert blend.level_pct == maillard_floor(dense).level_pct


def test_blend_reports_unresolved_labels_of_every_component():
    a = BeanProps(process='Washed', varieties='Zorglub')
    b = BeanProps(process='Washed', varieties='Machin')
    blend = maillard_floor_blend([(a, 0.5), (b, 0.5)])
    assert len(blend.unresolved) == 2


# ── Corroboration ────────────────────────────────────────────────────────────

def test_bases_match_the_operator_measured_hand():
    """Valeurs Maillard réellement tenues par l'opérateur sur ses 10 derniers
    roasts (surclassements manuels du brûleur, donc non contaminés par le plan) :
    lavé 62, natural 54, anaérobie 53."""
    assert PROCESS_BASE['washed'][0] == pytest.approx(62.0, abs=1.0)
    assert PROCESS_BASE['natural'][0] == pytest.approx(54.0, abs=1.0)
    assert PROCESS_BASE['fermented'][0] == pytest.approx(53.0, abs=1.0)

"""Pure contracts used by the ALog repair dialog."""

import ast
from pathlib import Path

from tilauscope.alog_repair import (
    LEARNING_ADMITTED,
    LEARNING_EXCLUDED,
    LEARNING_UNREVIEWED,
    apply_learning_state,
    audit_alog,
    learning_state,
    read_alog_meta,
    selectable_roaster_name,
)


def test_repair_selects_canonical_legacy_roaster() -> None:
    available = ['Cormorant CR600g', 'Kaleido M6 Pro']

    assert selectable_roaster_name('Cormorant', available) == 'Cormorant CR600g'


def test_repair_leaves_unknown_roaster_empty() -> None:
    assert selectable_roaster_name('Workshop prototype', ['Cormorant CR600g']) == ''


def test_repair_resolves_unique_model_only_name() -> None:
    assert selectable_roaster_name(
        'Cyberroaster', ['ITOP Cyberroaster', 'Cormorant CR600g'],
    ) == 'ITOP Cyberroaster'


def test_repair_falls_back_to_artisan_machine_setup() -> None:
    assert selectable_roaster_name(
        '', ['ITOP Cyberroaster'], 'Cyberroaster',
    ) == 'ITOP Cyberroaster'


def test_repair_does_not_guess_an_ambiguous_model() -> None:
    assert selectable_roaster_name(
        'Pro', ['Kaleido M1 Pro', 'Kaleido M6 Pro'],
    ) == ''


# ── Learning state: admitted / not reviewed / excluded ───────────────────────
# The state used to be a single negative marker, so "reviewed and sound" and
# "never looked at" were the same file. That ambiguity is what let a pass
# through the list flag a whole corpus without anyone noticing.

def test_a_profile_with_no_marker_is_not_reviewed() -> None:
    """Every legacy file lands here — and it is still learned from."""
    assert learning_state({}) == LEARNING_UNREVIEWED


def test_the_positive_marker_reads_as_admitted() -> None:
    assert learning_state({'tilau_learning_admitted': True}) == LEARNING_ADMITTED


def test_the_veto_reads_as_excluded() -> None:
    assert learning_state({'tilau_exclude_learning': True}) == LEARNING_EXCLUDED


def test_the_veto_wins_when_a_file_carries_both_markers() -> None:
    """Hand-edited or crossed by a save: the conservative reading survives."""
    assert learning_state({'tilau_exclude_learning': True,
                           'tilau_learning_admitted': True}) == LEARNING_EXCLUDED


def test_setting_a_state_never_leaves_the_previous_marker_behind() -> None:
    """Two markers at once is how a file starts meaning two things."""
    excluded = apply_learning_state({}, LEARNING_EXCLUDED)
    admitted = apply_learning_state(excluded, LEARNING_ADMITTED)
    assert admitted == {'tilau_learning_admitted': True}
    unreviewed = apply_learning_state(admitted, LEARNING_UNREVIEWED)
    assert unreviewed == {}


def test_setting_a_state_leaves_every_other_field_untouched() -> None:
    data = {'title': 'Cortes', 'timex': [0.0, 1.0], 'weight': [400.0, 340.0, 'g']}
    out = apply_learning_state(data, LEARNING_EXCLUDED)
    assert {k: v for k, v in out.items() if k != 'tilau_exclude_learning'} == data
    assert data == {'title': 'Cortes', 'timex': [0.0, 1.0],
                    'weight': [400.0, 340.0, 'g']}   # input not mutated


# ── fast metadata read ───────────────────────────────────────────────────────
# The list audit reads a dozen fields instead of parsing the curves. It must
# reach the SAME verdict as a full parse, or the list lies about the archive.

_PROFILE = {
    'title': 'Cortes - Washed',
    'beans': 'uuid: 0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0\nLot 42',
    'weight': [400.0, 338.5, 'g'],
    'density': [712.0, 'g', 1, 'l'],
    'moisture_greens': 10.4,
    'greens_temp': 21.0,
    'whole_color': 58.0,
    'ground_color': 62.0,
    'ambientTemp': 22.5,
    'ambient_humidity': 47.0,
    'tilau_learning_admitted': True,
    # the bulk a fast read must never pay for
    'timex': [float(i) for i in range(3000)],
    'temp1': [180.0 + i * 0.01 for i in range(3000)],
    'temp2': [90.0 + i * 0.02 for i in range(3000)],
}


def _write(tmp_path: Path, data: dict) -> Path:
    fp = tmp_path / "profile.alog"
    fp.write_text(repr(data), encoding='utf-8')
    return fp


def test_fast_read_reaches_the_same_verdict_as_a_full_parse(tmp_path: Path) -> None:
    fp = _write(tmp_path, _PROFILE)
    full = ast.literal_eval(fp.read_text(encoding='utf-8'))
    fast = read_alog_meta(fp)
    assert fast is not None
    assert audit_alog(fast) == audit_alog(full) == []
    assert learning_state(fast) == learning_state(full) == LEARNING_ADMITTED


def test_fast_read_reports_the_same_missing_fields(tmp_path: Path) -> None:
    data = dict(_PROFILE)
    for gone in ('moisture_greens', 'whole_color', 'ambient_humidity', 'title'):
        del data[gone]
    fp = _write(tmp_path, data)
    full = ast.literal_eval(fp.read_text(encoding='utf-8'))
    fast = read_alog_meta(fp)
    assert fast is not None
    assert audit_alog(fast) == audit_alog(full)
    assert 'moisture_greens' in audit_alog(fast)


def test_fast_read_is_not_fooled_by_a_field_name_quoted_inside_a_value(
        tmp_path: Path) -> None:
    """A note that mentions a key must not be read as that key."""
    data = dict(_PROFILE)
    data['beans'] = "uuid: 0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0\nnote: 'whole_color': 0.0"
    fp = _write(tmp_path, data)
    fast = read_alog_meta(fp)
    assert fast is not None
    assert fast['whole_color'] == 58.0
    assert audit_alog(fast) == []


def test_fast_read_returns_none_on_an_unreadable_file(tmp_path: Path) -> None:
    """None is the signal to fall back to the full parse, not a silent verdict."""
    assert read_alog_meta(tmp_path / "does-not-exist.alog") is None

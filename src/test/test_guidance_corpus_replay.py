# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.

from __future__ import annotations

import json

import corpus_harness as H
import pytest
from guidance_corpus_replay import ReplayMetrics, corpus_summary, replay_profile
from tilauscope.guidance_core import GuidanceMode
from tilauscope.guidance_observer import ActionSource
from tilauscope.guidance_replay import match_alarm_automation, recorded_actions


@pytest.fixture(scope='module')
def corpus_replays() -> tuple[list[ReplayMetrics], list[ReplayMetrics]]:
    H.install_qt_shims()
    model = H.make_plan_model(H.CORPUS_DIR)
    paths = H.corpus_files()
    manual = [replay_profile(
        model, path, controls_observable=H.controls_observable_for(path)) for path in paths]
    alarms_only = [replay_profile(
        model, path, apply_manual_actions=False,
        controls_observable=H.controls_observable_for(path)) for path in paths]
    return manual, alarms_only


def test_every_non_alarm_slider_change_is_manual() -> None:
    profile = {
        'timex': [float(i) for i in range(8)],
        'timeindex': [1, 0, 0, 0, 0, 0, 6],
        'specialevents': [2, 3, 4, 5, 6],
        'specialeventstype': [3, 3, 3, 0, 0],
        'specialeventsvalue': [7.0, 6.5, 6.0, 4.0, 4.0],
        'specialeventsStrings': ['S2', '65%', 'Baisser le bruleur', '', ''],
        'alarmflag': [], 'alarmaction': [], 'alarmstrings': [],
    }

    actions = recorded_actions(profile)
    # The final duplicate Air=4 is removed, but S2 and prose remain manual.
    assert len(actions) == 4
    assert [(a.at_s, a.lever, a.value, a.source) for a in actions] == [
        (1.0, 3, 7.0, ActionSource.OPERATOR),
        (2.0, 3, 6.5, ActionSource.OPERATOR),
        (3.0, 3, 6.0, ActionSource.OPERATOR),
        (4.0, 0, 4.0, ActionSource.OPERATOR),
    ]


def test_alarm_slider_event_is_inferred_as_plan_automation() -> None:
    profile = {
        'timex': [float(i) for i in range(8)],
        'timeindex': [1, 0, 0, 0, 0, 0, 6],
        'specialevents': [3], 'specialeventstype': [3],
        'specialeventsvalue': [7.0], 'specialeventsStrings': ['A2 (S3)'],
        'alarmflag': [0, 1], 'alarmaction': [0, 6],
        'alarmstrings': ['', '60'],
    }

    actions = recorded_actions(profile)
    assert len(actions) == 1
    assert actions[0].source is ActionSource.ALARM_AUTOMATION


def test_live_alarm_contract_returns_slider_command() -> None:
    match = match_alarm_automation(
        label='A2 (S3)', lever=3, stored_value=7.0,
        flags=[0, 1], actions=[0, 6], commands=['', '60 # burner step'])

    assert match is not None
    assert (match.alarm_number, match.lever, match.command_pct) == (2, 3, 60.0)


@pytest.mark.parametrize(('flags', 'actions', 'commands', 'value'), (
    ([0, 0], [0, 6], ['', '60'], 7.0),       # disabled
    ([0, 1], [0, 3], ['', '60'], 7.0),       # another slider
    ([0, 1], [0, 6], ['', '55'], 7.0),       # another command
    ([0, 1], [0, 6], ['', 'invalid'], 7.0),  # non-numeric command
))
def test_live_alarm_contract_rejects_unproven_events(
    flags: list[int], actions: list[int], commands: list[str], value: float,
) -> None:
    assert match_alarm_automation(
        label='A2 (S3)', lever=3, stored_value=value,
        flags=flags, actions=actions, commands=commands) is None


def test_unproven_alarm_like_event_remains_manual() -> None:
    profile = {
        'timex': [float(i) for i in range(8)],
        'timeindex': [1, 0, 0, 0, 0, 0, 6],
        'specialevents': [3], 'specialeventstype': [3],
        'specialeventsvalue': [7.0], 'specialeventsStrings': ['A2 (S3)'],
        # Alarm 2 targets another slider: it cannot explain this event.
        'alarmflag': [0, 1], 'alarmaction': [0, 3],
        'alarmstrings': ['', '60'],
    }

    assert recorded_actions(profile)[0].source is ActionSource.OPERATOR


def test_full_alog_corpus_replays_through_guidance_session(
    corpus_replays: tuple[list[ReplayMetrics], list[ReplayMetrics]],
) -> None:
    metrics, _alarms_only = corpus_replays

    assert len(metrics) >= 10
    assert all(item.samples > 100 for item in metrics)
    assert sum(item.actions for item in metrics) > 0
    assert sum(item.automatic_actions for item in metrics) > 0
    assert sum(item.projection_count for item in metrics) > 100
    assert all(item.transitions[0] is GuidanceMode.PLAN for item in metrics)
    assert any(item.profile.startswith('otherroasters/cormorant/') for item in metrics)
    assert any(item.profile.startswith('otherroasters/kaleido/') for item in metrics)
    # The session must never acquire AUTO authority from recorded data.
    assert all(GuidanceMode.AUTO not in item.transitions for item in metrics)


def test_incomplete_recordings_are_explicitly_excluded() -> None:
    excluded = [path.relative_to(H.CORPUS_DIR).as_posix()
                for path in H.incomplete_corpus_files()]

    assert excluded == ['otherroasters/cormorant/#_26-04-20_1848.alog']


def test_curve_only_corpus_never_attributes_operator_gestures(
    corpus_replays: tuple[list[ReplayMetrics], list[ReplayMetrics]],
) -> None:
    metrics, _alarms_only = corpus_replays
    curve_only = [item for item in metrics if item.curve_only]

    assert len(curve_only) == 9
    assert all(item.observed_manual_actions == 0 for item in curve_only)
    assert all(item.observe_entries == 0 for item in curve_only)
    assert sum(item.inferred_phase_entries for item in curve_only) > 0


def test_fixture_control_capability_comes_from_roaster_and_slider_config() -> None:
    cormorant = H.CORPUS_DIR / 'otherroasters/cormorant/#1_26-02-24_1858.alog'
    scenario = H.control_scenario_for(cormorant)

    assert H.read_alog(cormorant)['roastertype'] == 'Cormorant'
    assert scenario.roaster_name == 'Cormorant'
    assert scenario.slider_visibilities == (0, 0, 0, 0)
    assert not H.controls_observable_for(cormorant)


def test_alarm_only_counterfactual_never_takes_manual_authority(
    corpus_replays: tuple[list[ReplayMetrics], list[ReplayMetrics]],
) -> None:
    _manual, metrics = corpus_replays

    assert sum(item.automatic_actions for item in metrics) > 0
    # With no manual action, only a physical risk may preempt PLAN.
    assert all(set(item.transitions) <= {
        GuidanceMode.PLAN, GuidanceMode.SAFETY_ONLY} for item in metrics)
    assert all(item.observe_entries == 0 for item in metrics)
    assert all(item.adaptive_entries == 0 for item in metrics)


def test_manual_corpus_exercises_all_non_auto_authorities(
    corpus_replays: tuple[list[ReplayMetrics], list[ReplayMetrics]],
) -> None:
    metrics, _alarms_only = corpus_replays

    assert sum(item.manual_actions for item in metrics) >= 900
    assert sum(item.observe_entries for item in metrics) > 0
    assert sum(item.adaptive_entries for item in metrics) > 0
    assert sum(item.safety_entries for item in metrics) > 0


def test_guidance_corpus_calibration_baseline(
    corpus_replays: tuple[list[ReplayMetrics], list[ReplayMetrics]],
) -> None:
    metrics, _alarms_only = corpus_replays
    expected = json.loads(
        (H.GOLDEN_PATH.parent / 'guidance_corpus.json').read_text(encoding='utf-8'))

    assert corpus_summary(metrics) == expected

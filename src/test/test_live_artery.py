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

"""L3 — the live artery: Artisan's sampling loop into the roast assistant.

This is the path that runs while coffee is actually in the drum, and the one
whose failures are hardest to see. Every consumer along it is wrapped in a broad
``except`` so that nothing can break Artisan's own refresh — a sound decision
for production and a terrible one for diagnosis, because a regression here
produces no traceback, no message, and no visible symptom beyond guidance that
quietly stops updating.

So the tests drive the real ``RoastDataBridge`` with a ``qmc`` double that grows
one sample at a time (see ``replay_qmc``), and assert on what comes *out*.
Counting emissions is the trick that makes swallowed failures visible: if an
exception were being absorbed mid-roast, the stream would come up short, and a
count is something a silent ``except`` cannot fake.

The widget layer above the bridge stays out of scope, as planned — it needs a
full ApplicationWindow. The bridge is the boundary where the artery is still
testable and still carries everything that matters.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import corpus_harness as H
import pytest
import replay_qmc as R
from replay_qmc import ReplayAw, ReplayQmc

if TYPE_CHECKING:
    from pathlib import Path

#: A tick must fit inside Artisan's ~1 Hz sampling period, but that budget is so
#: vast compared to what the tick actually costs that testing against it would
#: catch nothing. Measured on a full roast replay (337 ticks): mean 0.002 ms,
#: worst 0.011 ms. The thresholds below sit ~250x above the measured mean and
#: ~900x above the worst tick — far enough that GC pauses and a loaded machine
#: cannot reach them, close enough that a file read or a plan regeneration
#: creeping into the hot path (both explicitly forbidden there) does.
MAX_TICK_S = 0.010
MEAN_TICK_S = 0.0005


def make_bridge(qmc: ReplayQmc) -> tuple[Any, dict[str, list]]:
    """A real RoastDataBridge over a replay, with every signal captured."""
    from tilauscope.roast_bridge import RoastDataBridge

    bridge = RoastDataBridge(ReplayAw(qmc))
    seen: dict[str, list] = {'bt': [], 'et': [], 'ror': [], 'ambient': [],
                             'phase': [], 'roast_state': []}
    for signal, key in (
        (bridge.bt_updated, 'bt'),
        (bridge.et_updated, 'et'),
        (bridge.ror_updated, 'ror'),
        (bridge.phase_changed, 'phase'),
        (bridge.roast_state_changed, 'roast_state'),
    ):
        signal.connect(seen[key].append)
    bridge.ambient_updated.connect(
        lambda t, h: seen['ambient'].append((t, h)),  # two args -> one tuple
    )
    return bridge, seen


def expected_stream(values: list[float], *, positive_only: bool) -> list[float]:
    """What the bridge should emit: changed values only, starting from 0.0.

    ``positive_only`` mirrors the BT/ET guard, which drops Artisan's -1 "no
    reading" sentinel. RoR has no such guard on purpose — a negative rate of
    rise is the normal state right after charge.
    """
    out: list[float] = []
    last = 0.0
    for value in values:
        if positive_only and value <= 0:
            continue
        if value != last:
            out.append(value)
            last = value
    return out


def idle_qmc(**kwargs: Any) -> ReplayQmc:
    """A minimal replay with no curve, for the synthetic state/ambient tests."""
    return ReplayQmc(timex=[], et=[], bt=[], ror=[], **kwargs)


# ── the state machine around the tick ────────────────────────────────────────

def test_bridge_starts_idle(qapp: Any) -> None:  # noqa: ARG001
    bridge, _ = make_bridge(idle_qmc())
    assert bridge._current_phase == 'IDLE'


def test_phase_notification_is_announced_and_remembered(qapp: Any) -> None:  # noqa: ARG001
    bridge, seen = make_bridge(idle_qmc())
    bridge.notify_phase('MAI')
    assert seen['phase'] == ['MAI']
    assert bridge._current_phase == 'MAI'


def test_preheat_maps_onto_the_phase_stream(qapp: Any) -> None:  # noqa: ARG001
    """Preheat is not a separate channel — it becomes a phase, by design."""
    bridge, seen = make_bridge(idle_qmc())
    bridge.notify_preheat(True)
    bridge.notify_preheat(False)
    assert seen['phase'] == ['PREHEAT', 'IDLE']


def test_ending_a_roast_returns_the_phase_to_idle(qapp: Any) -> None:  # noqa: ARG001
    """Otherwise the next roast would start in the previous one's phase.

    That matters beyond bookkeeping: the ambient check below only runs in
    PREHEAT/DRY/IDLE, so a phase left on DEV would silently stop ambient
    updates for the whole of the following roast.
    """
    bridge, seen = make_bridge(idle_qmc())
    bridge.notify_phase('DEV')
    bridge.notify_roast_state(False)
    assert bridge._current_phase == 'IDLE'
    assert seen['roast_state'] == [False]


def test_starting_a_roast_does_not_touch_the_phase(qapp: Any) -> None:  # noqa: ARG001
    bridge, seen = make_bridge(idle_qmc())
    bridge.notify_phase('DRY')
    bridge.notify_roast_state(True)
    assert bridge._current_phase == 'DRY'
    assert seen['roast_state'] == [True]


# ── value filtering ──────────────────────────────────────────────────────────

def test_unchanged_readings_are_not_re_emitted(qapp: Any) -> None:  # noqa: ARG001
    """The assistant refreshes on every emission; repeats would be pure cost."""
    qmc = ReplayQmc(timex=[0, 1, 2, 3], et=[150.0] * 4, bt=[180.0] * 4,
                    ror=[5.0] * 4)
    bridge, seen = make_bridge(qmc)
    while qmc.advance():
        bridge.tick(10)
    assert seen['bt'] == [180.0]
    assert seen['et'] == [150.0]
    assert seen['ror'] == [5.0]


def test_artisan_no_reading_sentinel_is_dropped(qapp: Any) -> None:  # noqa: ARG001
    """-1 means "no reading", not a temperature of minus one degree."""
    qmc = ReplayQmc(
        timex=[0, 1, 2],
        et=[150.0, R.ARTISAN_SENTINEL, 151.0],
        bt=[180.0, R.ARTISAN_SENTINEL, 181.0],
        ror=[1.0, 2.0, 3.0],
    )
    bridge, seen = make_bridge(qmc)
    while qmc.advance():
        bridge.tick(10)
    assert R.ARTISAN_SENTINEL not in seen['bt']
    assert R.ARTISAN_SENTINEL not in seen['et']
    assert seen['bt'] == [180.0, 181.0]


def test_negative_rate_of_rise_is_emitted(qapp: Any) -> None:  # noqa: ARG001
    """RoR deliberately has no positive guard: it is negative after charge.

    Copying the BT/ET guard onto RoR would silence the entire post-charge drop,
    which is precisely the stretch the assistant needs to see.
    """
    qmc = ReplayQmc(timex=[0, 1, 2], et=[150.0] * 3, bt=[180.0] * 3,
                    ror=[-12.0, -4.0, 6.0])
    bridge, seen = make_bridge(qmc)
    while qmc.advance():
        bridge.tick(10)
    assert seen['ror'] == [-12.0, -4.0, 6.0]


# ── ambient: gating and thresholds ───────────────────────────────────────────

@pytest.mark.parametrize(('phase', 'should_emit'), [
    ('IDLE', True),
    ('PREHEAT', True),
    ('DRY', True),
    ('MAI', False),
    ('DEV', False),
    ('COOL', False),
])
def test_ambient_is_only_read_when_it_can_still_change_the_plan(
    qapp: Any, phase: str, should_emit: bool,  # noqa: ARG001
) -> None:
    """After drying, ambient conditions no longer move the plan — so don't look.

    This gate is what keeps a mid-roast plan regeneration from firing on a
    draught.
    """
    qmc = idle_qmc()
    qmc.ambientTemp = 25.0
    qmc.ambient_humidity = 60.0
    bridge, seen = make_bridge(qmc)
    bridge.notify_phase(phase)
    bridge.tick(10)
    assert bool(seen['ambient']) is should_emit


def test_ambient_only_reports_a_significant_change(qapp: Any) -> None:  # noqa: ARG001
    """Sensor jitter must not trigger work; a real shift must."""
    qmc = idle_qmc()
    qmc.ambientTemp, qmc.ambient_humidity = 20.0, 50.0
    bridge, seen = make_bridge(qmc)

    bridge.tick(10)                       # first read establishes the baseline
    assert seen['ambient'] == [(20.0, 50.0)]

    qmc.ambientTemp = 22.0                # +2 °C, below the 3 °C threshold
    bridge.tick(10)
    assert len(seen['ambient']) == 1

    qmc.ambientTemp = 24.0                # +4 °C from the baseline
    bridge.tick(10)
    assert seen['ambient'][-1] == (24.0, 50.0)

    qmc.ambient_humidity = 56.0           # +6 % RH, above the 5 % threshold
    bridge.tick(10)
    assert seen['ambient'][-1] == (24.0, 56.0)


@pytest.mark.parametrize(('source', 'device', 'channel'), [
    (3, 0, 1),   # extratemp1[0]
    (4, 0, 2),   # extratemp2[0]
    (5, 1, 1),   # extratemp1[1]
    (6, 1, 2),   # extratemp2[1]
])
def test_ambient_source_index_maps_to_the_right_channel(
    qapp: Any, source: int, device: int, channel: int,  # noqa: ARG001
) -> None:
    """Artisan packs (device, channel) into one integer; the unpacking must hold.

    The expected mapping is not derived from TilauScope's own arithmetic — that
    would only pin the code against itself. It is Artisan's convention, and
    ``test_ambient_decoding_agrees_with_artisan`` below checks the two
    implementations against each other on the same data.
    """
    qmc = idle_qmc()
    qmc.ambientTempSource = source
    for dev in range(2):
        for chan in (1, 2):
            qmc.set_extra(dev, chan, 10.0)   # decoys on every other channel
    qmc.set_extra(device, channel, 27.0)     # the one that should be read

    bridge, seen = make_bridge(qmc)
    bridge.tick(10)
    assert seen['ambient'], f'source {source} read nothing'
    assert seen['ambient'][-1][0] == 27.0


@pytest.mark.parametrize('source', [3, 4, 5, 6])
def test_ambient_decoding_agrees_with_artisan(qapp: Any, source: int) -> None:  # noqa: ARG001
    """TilauScope and Artisan must unpack the same integer the same way.

    Artisan decodes this index itself, in ``tgraphcanvas.ambientSourceAvg``;
    TilauScope re-implements the arithmetic in ``RoastDataBridge`` because it
    needs the *live* reading rather than Artisan's average over the roast. Two
    implementations of one convention is exactly the arrangement that drifts
    apart silently — and an upstream sync is when it would happen.

    The two cannot be compared numerically in general (one is a live value, the
    other a mean over CHARGE..DROP), so each channel is loaded with its own
    constant: the mean of a constant channel is that constant, which makes the
    two answers directly comparable and tells us they read the same channel.
    """
    qmc = idle_qmc()
    qmc.ambientTempSource = source
    qmc.bind_artisan_ambient_decoder()

    # A window Artisan's averaging can work over, and a distinct constant per
    # channel so the value identifies which one was read.
    samples = 4
    qmc.temp1 = [150.0] * samples
    qmc.temp2 = [180.0] * samples
    qmc.timeindex = [0, 0, 0, 0, 0, 0, samples - 1, 0]
    for dev in range(2):
        for chan in (1, 2):
            marker = 20.0 + dev * 2 + chan       # 21, 22, 23, 24
            for _ in range(samples):
                qmc.set_extra(dev, chan, marker)

    bridge, seen = make_bridge(qmc)
    bridge.tick(10)

    artisan = qmc.ambientSourceAvg(source)
    assert seen['ambient'], f'TilauScope read nothing for source {source}'
    tilau = seen['ambient'][-1][0]
    assert tilau == artisan, (
        f'source {source}: TilauScope reads {tilau}, Artisan reads {artisan} — '
        'the two decoders no longer agree on which channel this index means'
    )


def test_ambient_uses_the_realtime_scalar_before_recording_starts(
    qapp: Any,  # noqa: ARG001
) -> None:
    """Monitoring and recording read different arrays, and Artisan shapes them
    differently: a series per device while recording, a bare scalar per device
    while only monitoring. Reading the wrong one raises inside the bridge and is
    swallowed, so the symptom is ambient silently never updating.
    """
    qmc = idle_qmc()
    qmc.ambientTempSource = 3
    qmc.flagstart = False                 # monitoring, not recording
    qmc.RTextratemp1[0] = 26.0
    qmc.extratemp1[0] = []                # recorded series still empty

    bridge, seen = make_bridge(qmc)
    bridge.tick(10)
    assert seen['ambient'], 'nothing read while monitoring — wrong array?'
    assert seen['ambient'][-1][0] == 26.0


def test_ambient_ignores_a_sentinel_reading(qapp: Any) -> None:  # noqa: ARG001
    qmc = idle_qmc()
    qmc.ambientTempSource = 3
    qmc.set_extra(0, 1, R.ARTISAN_SENTINEL)
    bridge, seen = make_bridge(qmc)
    bridge.tick(10)
    assert not seen['ambient']


# ── resilience: what the bridge absorbs, and what it does not ────────────────

def test_a_tick_on_an_empty_qmc_is_harmless(qapp: Any) -> None:  # noqa: ARG001
    """Ticks arrive before the first sample; that must not raise."""
    bridge, seen = make_bridge(idle_qmc())
    bridge.tick(10)
    assert seen['bt'] == [] and seen['et'] == [] and seen['ror'] == []


def test_a_missing_qmc_attribute_is_absorbed(qapp: Any) -> None:  # noqa: ARG001
    """Artisan's shape varies across versions; a missing array must not kill the
    tick, because the tick is what keeps the assistant alive."""
    qmc = idle_qmc()
    del qmc.temp2
    bridge, seen = make_bridge(qmc)
    bridge.tick(10)
    assert seen['bt'] == []


def test_an_unexpected_failure_is_not_absorbed_by_the_bridge(
    qapp: Any,  # noqa: ARG001
) -> None:
    """The bridge absorbs IndexError/TypeError/AttributeError and nothing else.

    This is the boundary worth pinning. Anything outside that trio travels up to
    the broad guard in ``update_ui_from_artisan``, which logs it — so it stays
    diagnosable. Widening the bridge's own except clause would move failures
    from "logged" to "invisible", and this test is what would notice.
    """
    class Exploding(list):
        def __getitem__(self, item: Any) -> Any:
            raise ValueError('sensor decoding failed')

    qmc = idle_qmc()
    qmc.temp2 = Exploding([1.0])
    bridge, _ = make_bridge(qmc)
    with pytest.raises(ValueError, match='sensor decoding failed'):
        bridge.tick(10)


# ── full replay against the recorded corpus ──────────────────────────────────

@pytest.mark.slow
@pytest.mark.parametrize('fixture', H.corpus_files(), ids=lambda p: p.name)
def test_replaying_a_real_roast_emits_the_recorded_curve(
    qapp: Any, fixture: Path,  # noqa: ARG001
) -> None:
    """Every recorded sample must come out the other end of the bridge.

    Emission counts are the point. The bridge swallows three exception types
    per channel; if one were firing mid-roast the stream would simply be short,
    with nothing logged and nothing raised. Comparing against the expected
    filtered stream is what turns that silence into a failure.
    """
    qmc = R.load_replay(fixture)
    bridge, seen = make_bridge(qmc)

    ticks = 0
    while qmc.advance():
        bridge.tick(10)
        ticks += 1

    assert ticks == len(qmc), 'replay stopped before the end of the roast'
    assert seen['bt'] == expected_stream(qmc.temp2, positive_only=True)
    assert seen['et'] == expected_stream(qmc.temp1, positive_only=True)
    assert seen['ror'] == expected_stream(qmc.delta2, positive_only=False)


@pytest.mark.slow
def test_a_tick_stays_far_inside_the_one_hertz_budget(qapp: Any) -> None:  # noqa: ARG001
    """The tick runs on Artisan's sampling thread, once a second.

    The margin here is enormous on purpose. What this catches is not a slow
    machine but a change of nature in the hot path — a file read, a plan
    regeneration, a corpus scan — which shows up as orders of magnitude, not
    percent.
    """
    qmc = R.load_replay(H.corpus_files()[0])
    bridge, _ = make_bridge(qmc)

    durations: list[float] = []
    while qmc.advance():
        started = time.perf_counter()
        bridge.tick(10)
        durations.append(time.perf_counter() - started)

    worst = max(durations)
    mean = sum(durations) / len(durations)
    assert worst < MAX_TICK_S, f'slowest tick {worst * 1000:.1f} ms'
    assert mean < MEAN_TICK_S, f'mean tick {mean * 1000:.1f} ms'

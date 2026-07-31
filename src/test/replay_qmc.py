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

"""A ``qmc`` double that replays a recorded roast the way Artisan produces it.

The live artery is driven by Artisan's sampling loop: every sample *appends* to
``timex``/``temp1``/``temp2``, and everything downstream reads ``[-1]``. A test
that hands the consumer a complete array is not testing that path — it is
testing a different one that happens to share a name.

So this double grows. :meth:`ReplayQmc.advance` appends exactly one sample, and
the arrays are only ever as long as the roast has got. Replaying a fixture from
CHARGE to DROP therefore walks the consumer through the same sequence of states
a real roast does, at whatever speed the test wants.

RoR deserves a note. Artisan does not store ``delta2`` in the profile (it is
recomputed on load), so the replay borrows the L2 harness to derive the real
curve with Artisan's own algorithm rather than inventing one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

import corpus_harness as H

if TYPE_CHECKING:
    from pathlib import Path

#: How Artisan encodes "no reading" in a temperature array.
ARTISAN_SENTINEL: Final[float] = -1.0


class ReplayQmc:
    """The subset of ``qmc`` the live artery actually reads, replayed sample by sample.

    Attribute names and shapes mirror Artisan exactly, including the awkward
    ones: ``extratemp1`` is a list of series (one per device) while
    ``RTextratemp1`` is a flat list of scalars, one per device, used while
    monitoring before recording starts. Consumers branch on ``flagstart`` to
    pick between them, so a double that flattened the difference would let a
    real bug through.
    """

    def __init__(
        self,
        timex: list[float],
        et: list[float],
        bt: list[float],
        ror: list[float],
        extra_devices: int = 8,
    ) -> None:
        self._src_timex = timex
        self._src_et = et
        self._src_bt = bt
        self._src_ror = ror
        self._cursor = 0

        # Live arrays — empty at CHARGE, one sample longer per advance().
        self.timex: list[float] = []
        self.temp1: list[float] = []
        self.temp2: list[float] = []
        self.delta1: list[float] = []
        self.delta2: list[float] = []

        # Extra channels: recorded series per device, plus the real-time
        # scalars Artisan keeps while only monitoring.
        self.extratemp1: list[list[float]] = [[] for _ in range(extra_devices)]
        self.extratemp2: list[list[float]] = [[] for _ in range(extra_devices)]
        self.RTextratemp1: list[float] = [0.0] * extra_devices
        self.RTextratemp2: list[float] = [0.0] * extra_devices

        # Recording state. flagon = monitoring, flagstart = recording.
        self.flagon: bool = True
        self.flagstart: bool = True

        # Ambient configuration. Source 0 means "no channel configured, use the
        # one-shot value" — which is what every fixture in the corpus does.
        self.ambientTemp: float = 0.0
        self.ambient_humidity: float = 0.0
        self.ambientTempSource: int = 0
        self.ambientHumiditySource: int = 0

        self.mode: str = 'C'
        self.timeindex: list[int] = [-1, 0, 0, 0, 0, 0, 0, 0]
        # Artisan's own ambient decoder bounds-checks against this list.
        self.extradevices: list[int] = [0] * extra_devices

    def bind_artisan_ambient_decoder(self) -> None:
        """Attach Artisan's real ``ambientSourceAvg`` to this double.

        Used to cross-check TilauScope's ambient-source decoding against the
        reference implementation rather than against itself. Same trick as the
        L2 harness uses for ``recomputeDeltas``: keep Artisan's algorithm, fake
        only the state it reads.
        """
        import types

        H.install_qt_shims()   # artisanlib.canvas needs them to import at all
        from artisanlib.canvas import tgraphcanvas

        self.ambientSourceAvg = types.MethodType(  # type: ignore[attr-defined]
            tgraphcanvas.ambientSourceAvg, self,
        )

    # ── replay control ───────────────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self._src_timex)

    @property
    def exhausted(self) -> bool:
        return self._cursor >= len(self._src_timex)

    def advance(self) -> bool:
        """Append the next recorded sample. False once the roast is over."""
        if self.exhausted:
            return False
        i = self._cursor
        self.timex.append(self._src_timex[i])
        self.temp1.append(self._src_et[i])
        self.temp2.append(self._src_bt[i])
        self.delta2.append(self._src_ror[i])
        self._cursor += 1
        return True

    def set_extra(self, device: int, channel: int, value: float) -> None:
        """Push a value on an extra channel, into whichever array is live.

        ``channel`` is 1 or 2, matching Artisan's extratemp1/extratemp2 naming.
        """
        recorded = self.extratemp1 if channel == 1 else self.extratemp2
        realtime = self.RTextratemp1 if channel == 1 else self.RTextratemp2
        recorded[device].append(value)
        realtime[device] = value


class ReplayAw:
    """Stands in for Artisan's ApplicationWindow: the bridge only wants ``qmc``."""

    def __init__(self, qmc: ReplayQmc) -> None:
        self.qmc = qmc


def load_replay(path: Path, model: Any | None = None) -> ReplayQmc:
    """Build a replay of one corpus fixture, from CHARGE to DROP.

    RoR comes from ``_get_delta_bt``, i.e. Artisan's real recompute path, so the
    stream the bridge sees is the stream it would see in production rather than
    a plausible-looking invention.
    """
    # Deriving RoR pulls artisanlib, which needs the Qt shims in place. Doing it
    # here rather than in the caller keeps the requirement with the code that
    # actually has it; install_qt_shims() is idempotent.
    H.install_qt_shims()
    model = model or H.make_plan_model(path.parent)
    ror, timex, bt, _tp_index, _phases = model._get_delta_bt(path.name)

    profile = H.read_alog(path)
    timeindex = profile['timeindex']
    start, end = timeindex[0], timeindex[6]
    et = [float(v) for v in profile['temp1'][start:end]]

    # _get_delta_bt slices on the same window; guard against drift rather than
    # silently zipping mismatched arrays.
    if not (len(ror) == len(timex) == len(bt) == len(et)):
        raise ValueError(
            f'{path.name}: replay arrays disagree — '
            f'ror={len(ror)} timex={len(timex)} bt={len(bt)} et={len(et)}',
        )

    return ReplayQmc(
        timex=[float(v) for v in timex],
        et=et,
        bt=[float(v) for v in bt],
        ror=[float(v) for v in ror],
    )

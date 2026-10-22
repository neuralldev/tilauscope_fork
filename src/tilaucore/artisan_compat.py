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
# Tilau 2025-2026

"""The few Artisan rules a roast file is read with, for the shared library.

tilaucore cannot import Artisan (artisanlib.util), so it holds these as they
are written there; test_artisan_compat checks both give the same answers.

The RoR of a recorded roast is computed with Artisan's standard method only
(differences over the delta span, then decaying-weights smoothing): the method
TilauScope uses, whatever variant Artisan offers besides.
"""

from __future__ import annotations

import codecs
import math
from dataclasses import dataclass
from typing import Any, Final

from tilaucore.numeric import interp, np_sum

weight_units: Final[tuple[str, str, str, str]] = ('g', 'Kg', 'lb', 'oz')

_LB_PER_KG: Final[float] = 2.20462262185
_WEIGHT_CONV_TABLE = (
    #  g                        Kg                      lb                  oz
    (1.,                        0.001,                  _LB_PER_KG/1000,    _LB_PER_KG*16/1000),  # g
    (1000.,                     1.,                     _LB_PER_KG,         _LB_PER_KG*16),       # Kg
    (1000/_LB_PER_KG,           1/_LB_PER_KG,           1.,                 16.),                 # lb
    (1000/(_LB_PER_KG*16),      1/(_LB_PER_KG*16),      1/16,               1.),                  # oz
)


def convertWeight(v: float, i: int, o: int) -> float:  # noqa: N802  (Artisan's name)
    if 0 <= i < 4 and 0 <= o < 4:
        return v * _WEIGHT_CONV_TABLE[i][o]
    raise IndexError(f'index error in convertWeight({v},{i},{o})')


def decodeLocalStrict(x: Any | None, default: str = '') -> str:  # noqa: N802  (Artisan's name)
    if x is None:
        return default
    try:
        return codecs.unicode_escape_decode(x)[0]
    except Exception:  # noqa: BLE001  pylint: disable=broad-except
        return default


def events_internal_to_external_value(v: float | None) -> int:
    if v is None:
        return 0
    if -1.0 <= v <= 1.0:
        return 0
    if v < -1.0:
        return -(int(round(abs(v)*10)) - 10)
    return int(round(v*10)) - 10


def fromFtoCstrict(Ffloat: float) -> float:  # noqa: N802,N803  (Artisan's name)
    if Ffloat == -1:
        return Ffloat
    return (Ffloat-32.0)*(5.0/9.0)


def fromCtoFstrict(Cfloat: float) -> float:  # noqa: N802,N803  (Artisan's name)
    if Cfloat == -1:
        return Cfloat
    return (Cfloat*9.0/5.0)+32.0


def RoRfromFtoCstrict(FRoR: float) -> float:  # noqa: N802,N803  (Artisan's name)
    if FRoR == -1:
        return FRoR
    return FRoR*(5.0/9.0)


def RoRfromCtoFstrict(CRoR: float) -> float:  # noqa: N802,N803  (Artisan's name)
    if CRoR == -1:
        return CRoR
    return CRoR*9.0/5.0


def convertTemp(t: float, source_unit: str, target_unit: str) -> float:  # noqa: N802  (Artisan's name)
    if source_unit in ('', target_unit) or target_unit == '':
        return t
    if source_unit == 'C':
        return fromCtoFstrict(t)
    return fromFtoCstrict(t)


def _float(value: Any) -> float:
    return math.nan if value is None else float(value)


def _linspace(start: float, stop: float, num: int) -> list[float]:
    """numpy.linspace(start, stop, num)."""
    if num == 1:
        return [start]
    div = num - 1
    delta = stop - start
    step = delta / div
    if step == 0:
        out = [(i / div) * delta + start for i in range(num)]
    else:
        out = [i * step + start for i in range(num)]
    out[-1] = stop
    return out


def _divide(a: float, b: float) -> float:
    """a / b as NumPy gives it: inf or NaN instead of an error."""
    if b != 0:
        return a / b
    if a == 0 or math.isnan(a) or math.isnan(b):
        return math.nan
    return math.copysign(math.inf, a) * math.copysign(1.0, b)


def fill_gaps(ll: list, interpolate_max: int = 3) -> list[float]:
    arr = [_float(v) for v in ll]
    valid = [i for i, v in enumerate(arr) if v != -1]
    if not valid:
        return arr
    for i in range(valid[0]):
        arr[i] = arr[valid[0]]
    for start, end in zip(valid[:-1], valid[1:], strict=True):
        gap = end - start - 1
        if 0 < gap <= interpolate_max:
            arr[start + 1:end] = _linspace(arr[start], arr[end], gap + 2)[1:-1]
    return arr


def medfilt(x: list[float], k: int) -> list[float]:
    """Length-k median filter; boundaries extended by repeating endpoints."""
    if not x:
        return x
    k2 = (k - 1) // 2
    out = []
    for r in range(len(x)):
        window = [x[min(max(r + o, 0), len(x) - 1)] for o in range(-k2, k2 + 1)]
        out.append(math.nan if any(math.isnan(v) for v in window) else sorted(window)[k2])
    return out


def _smooth_slice(a: list[float], b: list[float], window_len: int, medfilt_factor: int,
                  filter_dropouts: bool) -> list[float]:
    """Artisan's smooth_slice with decay smoothing, re-sampled to linear time and back."""
    a_mod = _linspace(a[0], a[-1], len(a))
    b = interp(a_mod, a, b, b[0], b[-1])
    res = b
    if filter_dropouts and medfilt_factor % 2 == 1:  # Artisan refuses an even length and keeps b
        res = medfilt(b, medfilt_factor)
    if window_len > 2:
        # Artisan smooths b, not the median-filtered values.
        weights = [float(w) for w in range(1, window_len + 1)]
        res = []
        for i, v in enumerate(b):
            seq = b[max(0, i - window_len + 1):i + 1]
            w = weights[max(0, window_len - len(seq)):]
            if not w:
                res.append(v)
            else:
                res.append(np_sum([s * k for s, k in zip(seq, w, strict=True)]) / np_sum(w))
    return interp(a, a_mod, res, res[0], res[-1])


def smooth_list(aa: list, b: list, window_len: int = 7, medfilt_factor: int = 3,
                filter_dropouts: bool = False) -> list[float]:
    """Artisan's smooth_list with decay smoothing: -1 readings stay gaps, each run between them is smoothed."""
    values = [_float(v) for v in b]
    if len(aa) > 1 and len(aa) == len(b) and (filter_dropouts or window_len > 2):
        a = [float(v) for v in aa]
        out: list[float] = []
        i = 0
        while i < len(values):
            j = i
            dropped = values[i] == -1
            while j < len(values) and (values[j] == -1) == dropped:
                j += 1
            if dropped:
                out += [math.nan] * (j - i)
            else:
                out += _smooth_slice(a[i:j], values[i:j], window_len, medfilt_factor, filter_dropouts)
            i = j
    else:
        out = values
    return [math.nan if v == -1 else v for v in out]


@dataclass(frozen=True)
class RoRSettings:
    """What Artisan's settings say of the RoR of a recorded roast."""
    curvefilter: int = 3
    interpolate_drops: bool = True
    delta_samples: int = 6
    delta_span_s: float = 0.0  # when set, each roast's delta_samples come from it and its own sampling interval
    delta_filter: int = 7
    median_filter_factor: int = 3
    filter_dropouts: bool = True
    limit: bool = True
    limit_min: int = -10
    limit_max: int = 45


def profile_sampling_interval(profile: dict) -> float:
    """The sampling interval Artisan reads a loaded profile with, in seconds."""
    interval = profile.get('samplinginterval')
    if isinstance(interval, (int, float)) and interval > 0:
        return float(interval)
    timex = profile.get('timex') or []
    if len(timex) > 2:
        return max(0.1, (timex[-1] - timex[0]) / (len(timex) - 1))
    return 1.0  # Artisan's default sampling


def delta_samples(span_s: float, interval_s: float) -> int:
    """Artisan's updateDeltaSamples: the readings one RoR value spans."""
    return max(1, int(round(span_s / interval_s)))


def compute_deltas(timex: list[float], temp: list, ds: int, delta_filter: int, roast_start_idx: int,
                   roast_end_idx: int, medfilt_factor: int, filter_dropouts: bool, limit_ror: bool,
                   ror_limit_min: int, ror_limit_max: int) -> list[float | None]:
    """Artisan's computeDeltas, standard method: differences over ds samples, then smoothing."""
    tx = [float(t) for t in timex]
    ntemp = [0.0 if x is None else float(x) for x in temp]
    z1 = [_divide(ntemp[i + ds] - ntemp[i], (tx[i + ds] - tx[i]) / 60.) for i in range(len(ntemp) - ds)]
    if len(tx) > len(z1):
        z1 = [z1[0] if z1 else 0.] * (len(tx) - len(z1)) + z1
    delta = smooth_list(tx, z1, window_len=int(round(delta_filter / 2.)), medfilt_factor=medfilt_factor,
                        filter_dropouts=filter_dropouts)
    return [d if (roast_start_idx <= i <= roast_end_idx) and (not limit_ror or ror_limit_min < d < ror_limit_max)
            else None for i, d in enumerate(delta)]


def recompute_bt_deltas(timex: list[float], charge_idx: int, drop_idx: int, bt: list,
                        settings: RoRSettings, recording: bool = False) -> list[float | None]:
    """The BT half of Artisan's recomputeDeltas."""
    return compute_deltas(timex, bt, max(1, settings.delta_samples), settings.delta_filter,
                          charge_idx if charge_idx > -1 else 0, drop_idx if drop_idx > 0 else len(timex),
                          settings.median_filter_factor, settings.filter_dropouts and not recording,
                          settings.limit, settings.limit_min, settings.limit_max)

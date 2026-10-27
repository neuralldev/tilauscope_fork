# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2025-2026 Tilau
# This file is part of TilauScope.

"""The NumPy and SciPy arithmetic the plan uses, in the standard library.

The tablet has no NumPy (no wheel for its Python). Each function computes what
its NumPy or SciPy counterpart computes, in the same order of operations, so the
plan gives the same numbers on both apps.
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Sequence

_PAIRWISE_BLOCK = 128


def _pairwise(values: Sequence[float], start: int, n: int) -> float:
    """NumPy's pairwise summation of values[start:start + n]."""
    if n < 8:
        total = -0.0
        for i in range(start, start + n):
            total += values[i]
        return total
    if n <= _PAIRWISE_BLOCK:
        r = [values[start + j] for j in range(8)]
        i = 8
        while i < n - n % 8:
            for j in range(8):
                r[j] += values[start + i + j]
            i += 8
        total = (r[0] + r[1]) + (r[2] + r[3]) + ((r[4] + r[5]) + (r[6] + r[7]))
        for k in range(i, n):
            total += values[start + k]
        return total
    half = n // 2
    half -= half % 8
    return _pairwise(values, start, half) + _pairwise(values, start + half, n - half)


def np_sum(values: Sequence[float]) -> float:
    """numpy.sum of a 1-D float sequence."""
    return _pairwise([float(v) for v in values], 0, len(values))


def mean(values: Sequence[float]) -> float:
    """numpy.mean of a non-empty 1-D sequence."""
    return np_sum(values) / len(values)


def median(values: Sequence[float]) -> float:
    """numpy.median of a non-empty 1-D sequence without NaN."""
    ordered = sorted(float(v) for v in values)
    n = len(ordered)
    if n % 2:
        return ordered[n // 2]
    return mean(ordered[n // 2 - 1:n // 2 + 1])


def clip(value: float, low: float, high: float) -> float:
    """numpy.clip of one value; NaN stays NaN."""
    if value < low:
        return low
    if value > high:
        return high
    return value


def round_half_even(value: float, decimals: int) -> float:
    """numpy.round: scaled, rounded half to even, scaled back."""
    scale = 10.0 ** decimals
    scaled = value * scale
    if math.isnan(scaled) or math.isinf(scaled):
        return value
    return math.copysign(round(scaled) / scale, scaled)  # -0.004 rounds to -0.0, as NumPy


def arange(start: float, stop: float, step: float) -> list[float]:
    """numpy.arange for floats: start + i * (second - first)."""
    n = max(0, math.ceil((stop - start) / step))
    if n == 0:
        return []
    if n == 1:
        return [start]
    delta = (start + step) - start
    return [start, start + delta] + [start + i * delta for i in range(2, n)]


_LIKELY_IN_CACHE = 8


def _search(key: float, arr: list[float], guess: int) -> int:
    """NumPy's binary_search_with_guess: the same index even when arr is not sorted."""
    n = len(arr)
    if key > arr[n - 1]:
        return n
    if key < arr[0]:
        return -1
    if n <= 4:
        i = 1
        while i < n and key >= arr[i]:
            i += 1
        return i - 1
    guess = max(1, min(guess, n - 3))
    imin, imax = 0, n
    if key < arr[guess]:
        if key < arr[guess - 1]:
            imax = guess - 1
            if guess > _LIKELY_IN_CACHE and key >= arr[guess - _LIKELY_IN_CACHE]:
                imin = guess - _LIKELY_IN_CACHE
        else:
            return guess - 1
    else:
        if key < arr[guess + 1]:
            return guess
        if key < arr[guess + 2]:
            return guess + 1
        imin = guess + 2
        if guess < n - _LIKELY_IN_CACHE - 1 and key < arr[guess + _LIKELY_IN_CACHE]:
            imax = guess + _LIKELY_IN_CACHE
    while imin < imax:
        mid = imin + ((imax - imin) >> 1)
        if key >= arr[mid]:
            imin = mid + 1
        else:
            imax = mid
    return imin - 1


def interp(x: Sequence[float], xp: Sequence[float], fp: Sequence[float],
           left: float, right: float) -> list[float]:
    """numpy.interp with left and right given, step for step (also on a time that runs back)."""
    xp = [float(v) for v in xp]
    fp = [float(v) for v in fp]
    if len(xp) == 1:
        return [left if value < xp[0] else right if value > xp[0] else fp[0] for value in x]
    last = len(xp) - 1
    out = []
    j = 0
    for value in x:
        if math.isnan(value):
            out.append(value)
            continue
        j = _search(value, xp, j)
        if j == -1:
            out.append(left)
        elif j == last + 1:
            out.append(right)
        elif j == last or xp[j] == value:
            out.append(fp[j])
        else:
            # NumPy is built with fused multiply-add: one rounding, not two.
            slope = (fp[j + 1] - fp[j]) / (xp[j + 1] - xp[j])
            result = math.fma(slope, value - xp[j], fp[j])
            if math.isnan(result):
                result = math.fma(slope, value - xp[j + 1], fp[j + 1])
                if math.isnan(result) and fp[j] == fp[j + 1]:
                    result = fp[j]
            out.append(result)
    return out


def moving_average(values: Sequence[float], win: int) -> list[float]:
    """numpy.convolve(values, ones(win) / win, mode='same'), term by term.

    NumPy hands these sums to the system BLAS, whose order of additions differs
    between machines; the last bit may differ from NumPy's, never more.
    """
    weight = 1.0 / win
    full = []
    for k in range(len(values) + win - 1):
        total = 0.0
        for i in range(max(0, k - win + 1), min(len(values), k + 1)):
            total += values[i] * weight
        full.append(total)
    start = (min(len(values), win) - 1) // 2
    return full[start:start + max(len(values), win)]


def column_stats(rows: Sequence[Sequence[float]]) -> tuple[list[float], list[float], list[float]]:
    """numpy.nanmin, nanmax and nanmean along axis 0; a column of NaN only gives NaN."""
    lows, highs, means = [], [], []
    for column in zip(*rows, strict=True):
        known = [v for v in column if not math.isnan(v)]
        if not known:
            lows.append(math.nan)
            highs.append(math.nan)
            means.append(math.nan)
            continue
        lows.append(min(known))
        highs.append(max(known))
        total = 0.0
        for v in column:
            total += 0.0 if math.isnan(v) else v
        means.append(total / len(known))
    return lows, highs, means


def polyfit_line(x: Sequence[float], y: Sequence[float]) -> tuple[float, float]:
    """Least-squares line (slope, offset), as numpy.polyfit(x, y, 1) up to the last bits."""
    n = len(x)
    mx, my = math.fsum(x) / n, math.fsum(y) / n
    sxx = math.fsum((a - mx) * (a - mx) for a in x)
    sxy = math.fsum((a - mx) * (b - my) for a, b in zip(x, y, strict=True))
    slope = sxy / sxx
    return slope, my - slope * mx


def _sign(value: float) -> float:
    return math.nan if math.isnan(value) else (value > 0) - (value < 0)


def _edge_slope(h0: float, h1: float, m0: float, m1: float) -> float:
    d = ((2 * h0 + h1) * m0 - h0 * m1) / (h0 + h1)
    if _sign(d) != _sign(m0):
        return 0.0
    if _sign(m0) != _sign(m1) and abs(d) > 3.0 * abs(m0):
        return 3.0 * m0
    return d


class Pchip:
    """scipy.interpolate.PchipInterpolator(x, y), evaluated or differentiated once."""

    def __init__(self, x: Sequence[float], y: Sequence[float]) -> None:
        self.x = [float(v) for v in x]
        y = [float(v) for v in y]
        n = len(self.x)
        h = [self.x[i + 1] - self.x[i] for i in range(n - 1)]
        if n < 2 or min(h) <= 0:
            raise ValueError("`x` must be strictly increasing sequence.")  # SciPy's refusal
        m = [(y[i + 1] - y[i]) / h[i] for i in range(n - 1)]
        if n == 2:
            d = [m[0], m[0]]
        else:
            d = [0.0] * n
            for k in range(1, n - 1):
                if _sign(m[k]) != _sign(m[k - 1]) or m[k] == 0 or m[k - 1] == 0:
                    d[k] = 0.0
                else:
                    w1 = 2 * h[k] + h[k - 1]
                    w2 = h[k] + 2 * h[k - 1]
                    d[k] = 1.0 / ((w1 / m[k - 1] + w2 / m[k]) / (w1 + w2))
            d[0] = _edge_slope(h[0], h[1], m[0], m[1])
            d[-1] = _edge_slope(h[-1], h[-2], m[-1], m[-2])
        # CubicHermiteSpline coefficients, highest power first.
        self.c = []
        for i in range(n - 1):
            slope = (y[i + 1] - y[i]) / h[i]
            t = (d[i] + d[i + 1] - 2 * slope) / h[i]
            self.c.append((t / h[i], (slope - d[i]) / h[i] - t, d[i], y[i]))

    def _interval(self, value: float) -> int:
        return min(max(bisect.bisect_right(self.x, value) - 1, 0), len(self.x) - 2)

    def __call__(self, points: Sequence[float]) -> list[float]:
        out = []
        for value in points:
            i = self._interval(value)
            s = value - self.x[i]
            c0, c1, c2, c3 = self.c[i]
            out.append(c3 + c2 * s + c1 * (s * s) + c0 * (s * s * s))
        return out

    def derivative(self, points: Sequence[float]) -> list[float]:
        out = []
        for value in points:
            i = self._interval(value)
            s = value - self.x[i]
            c0, c1, c2, _ = self.c[i]
            out.append(c2 * 1 + (c1 * 2) * s + (c0 * 3) * (s * s))
        return out

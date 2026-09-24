"""Read-only profile fitting. No Artisan state or widgets are used by the worker."""
from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from tilauscope.tilauscope_types import (DEV_EVENT_PROMINENCE_C, find_flicks_crashes, marked,
                                         normalize_timeindex, which_roast_phase)

# Fitted trends, in the order the expert table lists them.
MODELS = ('quadratic', 'cubic', 'logarithmic')
# Below this deviation a passage is inside the RoR smoothing noise: never named.
NOTABLE_DELTA = DEV_EVENT_PROMINENCE_C


class AnalysisUnavailable(ValueError):
    """The message is a stable code translated by the view."""


@dataclass(frozen=True)
class AnalysisInput:
    times: tuple
    temperatures: tuple
    ror: tuple
    milestones: tuple
    temperature_unit: str
    ror_unit: str
    model: str = 'quadratic'
    period: str = 'dry'
    minimum_seconds: float = 5.0
    minimum_delta: float = 0.5
    fit_period: str = ''            # '' fits over the analysed period
    # Another roast used as the reference ('roast' model); RoR in ror_unit.
    reference_times: tuple = ()
    reference_temperatures: tuple = ()
    reference_ror: tuple = ()
    reference_milestones: tuple = ()
    reference_unit: str = 'C'


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    peak: float
    mean_absolute: float
    swing: float | None


@dataclass(frozen=True)
class RorEvent:
    """A real dip (crash) or bump (flick) of the measured RoR, whatever the reference."""
    kind: str
    time: float
    ror: float
    prominence: float


@dataclass(frozen=True)
class AnalysisResult:
    times: np.ndarray
    actual_ror: np.ndarray
    reference_ror: np.ndarray
    segments: tuple[Segment, ...]
    rmse_bt: float
    mse_bt: float
    rmse_ror: float
    r2_bt: float | None
    r2_ror: float | None
    mean_absolute: float
    fc_delta: float | None
    fc_time: float | None
    minimum: float
    maximum: float
    fit_start: float
    equation: str
    fc_ror: float | None = None
    dry_time: float | None = None
    drop_time: float = 0.0
    ror_slope: float = 0.0          # measured RoR trend, °C/min per minute
    reference_slope: float = 0.0
    events: tuple[RorEvent, ...] = ()


@dataclass(frozen=True)
class Observation:
    """One passage worth a look: kind is crash, flick, below, above or flat."""
    kind: str
    start: float
    end: float
    peak: float
    mean_absolute: float
    segment: int | None
    phase: int
    prominence: float = 0.0


def _r2(actual: np.ndarray, reference: np.ndarray) -> float | None:
    total = float(np.sum((actual - actual.mean()) ** 2))
    return 1.0 - float(np.sum((actual - reference) ** 2)) / total if total > 1e-12 else None


def _area(values: np.ndarray, times: np.ndarray) -> float:
    return float(np.trapezoid(np.abs(values), x=times))


def _slope(times: np.ndarray, values: np.ndarray) -> float:
    return float(np.polyfit(times / 60.0, values, 1)[0])


def _segments(times: np.ndarray, residuals: np.ndarray,
              minimum_seconds: float, minimum_delta: float) -> tuple[Segment, ...]:
    """Merge brief/small crossings to the left, sharing integration boundaries.

    The shared boundary sample belongs to the next segment's peak, as in Analyzer.
    """
    last = len(times) - 1
    starts = np.r_[0, np.flatnonzero(np.diff(np.sign(residuals))) + 1]
    groups: list[list[int]] = []
    for pos, first in enumerate(starts):
        end = int(starts[pos + 1]) if pos + 1 < len(starts) else last
        start = int(first)
        peak = float(np.max(np.abs(residuals[start:end if end < last else end + 1])))
        if groups and (times[end] - times[start] <= minimum_seconds
                       or peak <= minimum_delta
                       or np.sign(residuals[start]) == np.sign(residuals[groups[-1][0]])):
            groups[-1][1] = end
        elif end > start:
            groups.append([start, end])
    result: list[Segment] = []
    for start, end in groups:
        values = residuals[start:end + 1]
        own = values[:-1] if end < last else values
        peak = float(own[np.argmax(np.abs(own))])
        duration = float(times[end] - times[start])
        result.append(Segment(float(times[start]), float(times[end]), peak,
                              _area(values, times[start:end + 1]) / duration,
                              peak - result[-1].peak if result else None))
    return tuple(result)


def _period_start(period: str, ti: list, times: np.ndarray, charge: int, drop: int,
                  fc: int | None) -> int:
    if period == 'dry':
        if not marked(ti, 1) or not charge < ti[1] < drop:
            raise AnalysisUnavailable('dry')
        return ti[1]
    if period == 'crack':
        if fc is None:
            raise AnalysisUnavailable('crack')
        return max(charge + 1, int(np.searchsorted(times, times[fc] - 120)))
    raise AnalysisUnavailable('interval')


def _reference_roast(source: AnalysisInput) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The other roast's valid BT and RoR, in Celsius, timed from its own CHARGE."""
    ti = normalize_timeindex(source.reference_milestones)
    if not marked(ti, 0) or not marked(ti, 6) or source.reference_unit not in ('C', 'F'):
        raise AnalysisUnavailable('reference')
    try:
        times = np.asarray(source.reference_times, dtype=float)
        bt = np.asarray(source.reference_temperatures, dtype=float)
        ror = np.asarray(source.reference_ror, dtype=float)
    except (TypeError, ValueError) as exc:
        raise AnalysisUnavailable('reference') from exc
    charge, drop = ti[0], ti[6]
    if (times.ndim != 1 or len(times) != len(bt) or len(times) != len(ror)
            or not 0 <= charge < drop < len(times) or np.any(np.diff(times) <= 0)):
        raise AnalysisUnavailable('reference')
    part = slice(charge, drop + 1)
    valid = np.isfinite(times[part]) & np.isfinite(bt[part]) & (bt[part] != -1) & np.isfinite(ror[part])
    if np.count_nonzero(valid) < 6:
        raise AnalysisUnavailable('reference')
    t, bt, ror = times[part][valid] - times[charge], bt[part][valid], ror[part][valid]
    if source.reference_unit == 'F':
        bt = (bt - 32.0) / 1.8
    if source.ror_unit == 'F':
        ror = ror / 1.8
    return t, bt, ror


def _ror_events(times: np.ndarray, bt: np.ndarray, valid_bt: np.ndarray, ror: np.ndarray,
                charge: int, drop: int, phase_times: dict) -> tuple[RorEvent, ...]:
    """The project's crash/flick detector, run on the whole roast so TP recovery stays excluded."""
    span = slice(charge, drop + 1)
    searched = np.where(valid_bt[span], bt[span], np.inf)
    tp = int(np.argmin(searched[:max(1, int(np.searchsorted(times[span], 150)))]))
    series = [float(v) if np.isfinite(v) else None for v in ror[span]]
    flicks, crashes = find_flicks_crashes(series, list(times[span]), phase_times, tp,
                                          prominence=DEV_EVENT_PROMINENCE_C)
    events = [RorEvent('flick', e['time'], e['ror_value'], e['severity']) for e in flicks]
    events += [RorEvent('crash', e['time'], e['ror_value'], e['severity']) for e in crashes]
    return tuple(sorted(events, key=lambda e: e.time))


def analyze_profile(source: AnalysisInput) -> AnalysisResult:
    """Fit raw BT in Celsius and compare its derivative to the viewer's RoR.

    This is intentionally not an exact clone of Analyzer: its BT metrics use
    smoothed temperatures and its reference RoR passes through Artisan's delta
    machinery. Here raw BT and the analytical derivative are explicit choices.
    The 'roast' model compares with another roast aligned on CHARGE, like
    Analyzer's fit to background, and stops at the earlier of the two DROPs.
    """
    ti = normalize_timeindex(source.milestones)
    if not marked(ti, 0) or not marked(ti, 6):
        raise AnalysisUnavailable('charge_drop')
    try:
        times = np.asarray(source.times, dtype=float)
        bt = np.asarray(source.temperatures, dtype=float)
        ror = np.asarray(source.ror, dtype=float)
    except (TypeError, ValueError) as exc:
        raise AnalysisUnavailable('readings') from exc
    charge, drop = ti[0], ti[6]
    if (times.ndim != 1 or len(times) != len(bt) or len(times) != len(ror)
            or not 0 <= charge < drop < len(times)
            or not np.all(np.isfinite(times)) or np.any(np.diff(times) <= 0)):
        raise AnalysisUnavailable('readings')
    if source.temperature_unit not in ('C', 'F') or source.ror_unit not in ('C', 'F'):
        raise AnalysisUnavailable('units')
    # Missing BT is Artisan's -1 sentinel, checked before converting Fahrenheit.
    valid_bt = np.isfinite(bt) & (bt != -1)
    if source.temperature_unit == 'F':
        bt = (bt - 32.0) / 1.8
    if source.ror_unit == 'F':
        ror = ror / 1.8
    times = times - times[charge]
    fc = ti[2] if marked(ti, 2) and charge < ti[2] <= drop else None
    start = _period_start(source.period, ti, times, charge, drop, fc)
    end = drop
    if source.model == 'roast':
        ref_t, ref_bt, ref_ror = _reference_roast(source)
        if times[start] < ref_t[0]:
            raise AnalysisUnavailable('reference')
        end = min(drop, int(np.searchsorted(times, ref_t[-1], side='right')) - 1)
    if end - start < 5 or not np.all(valid_bt[start:end + 1]) or not np.all(np.isfinite(ror[start:end + 1])):
        raise AnalysisUnavailable('readings')
    window = times[start:end + 1]
    if source.model == 'roast':
        fit_start = start
        reference_bt = np.interp(window, ref_t, ref_bt)
        reference_ror = np.interp(window, ref_t, ref_ror)
        equation = ''
    else:
        fit_start = _period_start(source.fit_period or source.period, ti, times, charge, drop, fc)
        if source.model == 'logarithmic':
            # Start beyond TP, early enough to constrain the logarithm's curvature.
            if not np.all(valid_bt[charge:drop + 1]):
                raise AnalysisUnavailable('readings')
            tp = charge + int(np.argmin(bt[charge:fit_start + 1]))
            fit_start = int(np.searchsorted(times, times[tp] + .25 * (times[fit_start] - times[tp])))
        if drop - fit_start < 5 or not np.all(valid_bt[fit_start:drop + 1]):
            raise AnalysisUnavailable('readings')
        x, y = times[fit_start:drop + 1], bt[fit_start:drop + 1]
        if source.model in ('quadratic', 'cubic'):
            degree = 2 if source.model == 'quadratic' else 3
            polynomial = np.polynomial.Polynomial.fit(x, y, degree).convert()
            reference_bt = polynomial(window)
            reference_ror = polynomial.deriv()(window) * 60.0
            equation = ' + '.join(f'{c:.8g}·t^{i}' for i, c in enumerate(polynomial.coef))
        elif source.model == 'logarithmic':
            from scipy.optimize import curve_fit

            def logarithm(t, a, shift, offset):
                return a * np.log(t + shift) + offset

            try:
                coeffs, _ = curve_fit(logarithm, x, y, p0=(50., 1., -100.),
                                      bounds=([-np.inf, -x[0] + 1e-3, -np.inf],
                                              [np.inf, np.inf, np.inf]), maxfev=3000)
            except (RuntimeError, ValueError, FloatingPointError) as exc:
                raise AnalysisUnavailable('fit') from exc
            a, shift, offset = coeffs
            reference_bt = logarithm(window, *coeffs)
            reference_ror = 60.0 * a / (window + shift)
            equation = f'{a:.8g}·ln(t + {shift:.8g}) + {offset:.8g}'
        else:
            raise AnalysisUnavailable('fit')
    if not np.all(np.isfinite(reference_bt)) or not np.all(np.isfinite(reference_ror)):
        raise AnalysisUnavailable('fit')
    actual = ror[start:end + 1]
    residuals = actual - reference_ror
    mse = float(np.mean((bt[start:end + 1] - reference_bt) ** 2))
    fc_in_window = fc is not None and start <= fc <= end
    dry = ti[1] if marked(ti, 1) and charge < ti[1] < drop else None
    phase_times = {'dry_end': float(times[dry]) if dry is not None else None,
                   'fc_start': float(times[fc]) if fc is not None else None,
                   'drop': float(times[drop])}
    # A dip is a crash only below the reference, a bump a flick only above it:
    # the shoulder where a dip recovers back onto the trend is neither.
    events = tuple(e for e in _ror_events(times, bt, valid_bt, ror, charge, drop, phase_times)
                   if window[0] <= e.time <= window[-1]
                   and (1 if e.kind == 'flick' else -1) * np.interp(e.time, window, residuals)
                   >= source.minimum_delta)
    return AnalysisResult(
        window, actual, reference_ror,
        _segments(window, residuals, source.minimum_seconds, source.minimum_delta),
        float(np.sqrt(mse)), mse, float(np.sqrt(np.mean(residuals ** 2))),
        _r2(bt[start:end + 1], reference_bt), _r2(actual, reference_ror),
        _area(residuals, window) / float(window[-1] - window[0]),
        float(residuals[fc - start]) if fc_in_window else None,
        float(times[fc]) if fc_in_window else None,
        float(np.min(residuals)), float(np.max(residuals)), float(times[fit_start]), equation,
        float(actual[fc - start]) if fc_in_window else None,
        phase_times['dry_end'], phase_times['drop'], _slope(window, actual),
        _slope(window, reference_ror), events)


def analyze_all(source: AnalysisInput) -> dict[str, AnalysisResult | str]:
    """Every reference at once, so switching between them never recalculates.

    A reference that cannot be computed holds its AnalysisUnavailable code.
    """
    models = MODELS + (('roast',) if source.reference_times else ())
    results: dict[str, AnalysisResult | str] = {}
    for model in models:
        try:
            results[model] = analyze_profile(replace(source, model=model))
        except AnalysisUnavailable as exc:
            results[model] = str(exc)
    return results


def observations(result: AnalysisResult) -> tuple[Observation, ...]:
    """Passages to examine, in time order, then the overall RoR trend.

    A measured dip or bump comes first: it is a fact of the RoR itself. A
    passage far from the reference without one is only a deviation. Nothing
    under NOTABLE_DELTA is named.
    """
    phase_times = {'dry_end': result.dry_time, 'fc_start': result.fc_time,
                   'drop': float(result.times[-1])}

    def segment_at(time: float) -> int | None:
        for i, segment in enumerate(result.segments):
            if segment.start <= time <= segment.end:
                return i
        return None

    found: list[Observation] = []
    named: set[int] = set()
    for event in result.events:
        index = segment_at(event.time)
        segment = result.segments[index] if index is not None else None
        found.append(Observation(event.kind, segment.start if segment else event.time,
                                 segment.end if segment else event.time,
                                 segment.peak if segment else 0.0,
                                 segment.mean_absolute if segment else 0.0, index,
                                 which_roast_phase(event.time, phase_times), event.prominence))
        if index is not None:
            named.add(index)
    for index, segment in enumerate(result.segments):
        if index not in named and abs(segment.peak) >= NOTABLE_DELTA:
            found.append(Observation('below' if segment.peak < 0 else 'above', segment.start,
                                     segment.end, segment.peak, segment.mean_absolute, index,
                                     which_roast_phase(segment.start, phase_times)))
    found.sort(key=lambda o: o.start)
    if result.ror_slope >= 0:
        found.append(Observation('flat', float(result.times[0]), float(result.times[-1]),
                                 result.ror_slope, 0.0, None, 0))
    return tuple(found)

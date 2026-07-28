#!/usr/bin/env python3
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

"""
Extract thermal response characteristics from TilauScope/Artisan .alog files.

Analyzes preheat phases to build a thermal model for Skywalker FIR roaster:
- Ramp phase (0 to fuzzy zone): measure thermal mass and response lag
- Fuzzy/approach phase: measure overshoot braking effectiveness

Output: CSV with one row per preheat, plus aggregated statistics.
"""

import ast
import os
import csv
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Tuple
from datetime import datetime


@dataclass
class AmbientConditions:
    """Ambient conditions from .alog metadata."""
    temp: float  # °C
    humidity: float  # %
    pressure: float  # hPa
    timestamp: str


@dataclass
class ThermalMetrics:
    """Computed thermal response metrics."""
    roast_name: str
    ambient_temp: float
    ambient_humidity: float
    ambient_pressure: float

    # Ramp phase (0 to fuzzy zone start)
    ramp_duration_s: float
    ramp_mean_ror_c_per_min: float
    ramp_mean_burner_pct: float
    thermal_mass_c_per_pct_per_min: float
    response_lag_s: float

    # Fuzzy/approach phase (fuzzy zone to CHARGE)
    approach_duration_s: float
    approach_mean_ror_c_per_min: float
    approach_mean_burner_pct: float
    final_undershoot_c: float

    timestamp: str


def load_alog(alog_path: str) -> dict:
    """Load and parse an .alog file (latin-1 encoded Python dict)."""
    with open(alog_path, 'r', encoding='latin-1') as f:
        content = f.read()
    return ast.literal_eval(content)


def extract_preheat_phase(data: dict) -> Tuple[list, list, list, int, Optional[int]]:
    """
    Extract preheat phase data: timex, temp1 (BT), SV (burner %), CHARGE index.

    Returns:
        (timex, temp1_bt, sv_burner_pct, charge_idx, drop_idx)
    """
    timex = data.get('timex', [])
    temp1_bt = data.get('temp1', [])

    # Burner power is in extratemp1[1] (labeled "SV")
    extratemp1 = data.get('extratemp1', [])
    sv_burner_pct = extratemp1[1] if len(extratemp1) > 1 else []

    # CHARGE is at timeindex[0]
    charge_idx = data.get('timeindex', [0])[0]
    if charge_idx < 0 or charge_idx == 0:  # -1 or 0 means not marked
        return timex, temp1_bt, sv_burner_pct, None, None

    # DROP is at timeindex[1]
    drop_idx = data.get('timeindex', [0, 0])[1] if len(data.get('timeindex', [])) > 1 else None
    if drop_idx == 0:
        drop_idx = None

    return timex, temp1_bt, sv_burner_pct, charge_idx, drop_idx


def detect_fuzzy_zone_start(temp1_bt: list, sv_pct: list, charge_idx: int, lookback_s: int = 60) -> int:
    """
    Detect start of fuzzy zone (approach phase).

    In a typical preheat, the burner is ramped until ~20s before CHARGE,
    then cut hard to let temp coast down slightly (overshoot braking).
    The fuzzy zone is when the burner starts being cut/modulated.

    Heuristic: detect when SV drops sharply or stays at low/zero for extended period.
    For now, look for the last time SV was at high % (>70%), then fuzzy starts after that.

    Returns: index in preheat phase where fuzzy zone starts.
    """
    if charge_idx < 10:
        return 0

    # Look backwards from CHARGE to find last high SV
    for i in range(charge_idx - 1, max(0, charge_idx - lookback_s), -1):
        if i < len(sv_pct) and sv_pct[i] > 70:
            return i + 1

    # Fallback: if no high SV found in lookback, assume fuzzy starts 30s before CHARGE
    return max(0, charge_idx - 30)


def compute_ror(temps: list, times: list, window_s: int = 10) -> list:
    """Compute Rate of Rise in °C/min using sliding window."""
    ror = []
    for i in range(len(temps)):
        if i == 0:
            ror.append(0)
            continue

        # Find sample ~window_s ago
        j = i - 1
        while j >= 0 and (times[i] - times[j]) < window_s:
            j -= 1

        if j >= 0:
            dt_min = (times[i] - times[j]) / 60.0
            if dt_min > 0:
                dtemp = temps[i] - temps[j]
                ror.append(dtemp / dt_min)
            else:
                ror.append(0)
        else:
            ror.append(0)

    return ror


def measure_response_lag(temp1_bt: list, sv_pct: list, timex: list, start_idx: int, end_idx: int) -> float:
    """
    Measure response lag (delay from burner change to temperature change).

    Look for the largest burner transitions and measure how long until temp responds.
    """
    if start_idx >= end_idx or end_idx > len(sv_pct):
        return 0.0

    max_lag_s = 0.0
    transition_threshold = 20  # % change
    response_threshold = 0.3  # °C/min RoR to count as "response"

    # Find RoR during this phase
    ror = compute_ror(temp1_bt, timex)

    # Look for burner increases and measure response
    for i in range(start_idx, end_idx - 1):
        if i + 1 < len(sv_pct):
            burner_change = sv_pct[i + 1] - sv_pct[i]
            if burner_change > transition_threshold:
                # Burner increased; measure lag until RoR rises
                for j in range(i + 1, min(i + 60, end_idx)):  # Check next 60s
                    if ror[j] > response_threshold:
                        lag_s = timex[j] - timex[i]
                        max_lag_s = max(max_lag_s, lag_s)
                        break

    return max_lag_s


def compute_thermal_metrics(alog_path: str) -> Optional[ThermalMetrics]:
    """Extract and compute thermal metrics from a single .alog file."""
    try:
        data = load_alog(alog_path)
    except Exception as e:
        print(f"Error loading {alog_path}: {e}", file=sys.stderr)
        return None

    # Get roast metadata
    roast_name = data.get('title', Path(alog_path).stem)
    roast_iso_date = data.get('roastisodate', 'unknown')
    roast_time = data.get('roasttime', '00:00:00')
    ambient_temp = data.get('ambientTemp', 20.0)
    ambient_humidity = data.get('ambient_humidity', 50.0)
    ambient_pressure = data.get('ambient_pressure', 1013.0)
    timestamp = f"{roast_iso_date}T{roast_time}"

    # Extract preheat data
    timex, temp1_bt, sv_pct, charge_idx, drop_idx = extract_preheat_phase(data)

    if charge_idx is None or charge_idx < 10:
        return None

    # Ensure arrays are long enough
    if len(timex) < charge_idx or len(temp1_bt) < charge_idx or len(sv_pct) < charge_idx:
        return None

    # Get preheat duration
    preheat_duration_s = timex[charge_idx] if charge_idx < len(timex) else 0

    # Detect fuzzy zone start (approach phase)
    fuzzy_start_idx = detect_fuzzy_zone_start(temp1_bt, sv_pct, charge_idx)

    # Compute metrics for ramp phase (0 to fuzzy_start)
    if fuzzy_start_idx > 0:
        ramp_temps = temp1_bt[:fuzzy_start_idx]
        ramp_times = timex[:fuzzy_start_idx]
        ramp_sv = sv_pct[:fuzzy_start_idx]
    else:
        ramp_temps = []
        ramp_times = []
        ramp_sv = []

    ramp_duration_s = ramp_times[-1] if ramp_times else 0

    if ramp_duration_s > 0:
        ramp_mean_ror = (ramp_temps[-1] - ramp_temps[0]) / ramp_duration_s * 60
        ramp_mean_burner_pct = sum(ramp_sv) / len(ramp_sv) if ramp_sv else 0

        # Thermal mass: °C per % burner power per minute
        if ramp_mean_burner_pct > 0:
            thermal_mass = ramp_mean_ror / ramp_mean_burner_pct
        else:
            thermal_mass = 0
    else:
        ramp_mean_ror = 0
        ramp_mean_burner_pct = 0
        thermal_mass = 0

    # Measure response lag in ramp phase
    response_lag = measure_response_lag(temp1_bt, sv_pct, timex, 0, min(fuzzy_start_idx, charge_idx))

    # Compute metrics for approach phase (fuzzy_start to charge)
    if fuzzy_start_idx < charge_idx:
        approach_temps = temp1_bt[fuzzy_start_idx:charge_idx + 1]
        approach_times = timex[fuzzy_start_idx:charge_idx + 1]
        approach_sv = sv_pct[fuzzy_start_idx:charge_idx + 1]
    else:
        approach_temps = []
        approach_times = []
        approach_sv = []

    approach_duration_s = (approach_times[-1] - approach_times[0]) if approach_times and len(approach_times) > 1 else 0

    if approach_duration_s > 0:
        approach_mean_ror = (approach_temps[-1] - approach_temps[0]) / approach_duration_s * 60
        approach_mean_burner_pct = sum(approach_sv) / len(approach_sv) if approach_sv else 0
    else:
        approach_mean_ror = 0
        approach_mean_burner_pct = 0

    # Final undershoot: check if BT at CHARGE is below peak during approach
    final_undershoot = 0
    if approach_temps:
        peak_approach_temp = max(approach_temps)
        final_temp = approach_temps[-1]
        final_undershoot = peak_approach_temp - final_temp

    return ThermalMetrics(
        roast_name=roast_name,
        ambient_temp=ambient_temp,
        ambient_humidity=ambient_humidity,
        ambient_pressure=ambient_pressure,
        ramp_duration_s=ramp_duration_s,
        ramp_mean_ror_c_per_min=ramp_mean_ror,
        ramp_mean_burner_pct=ramp_mean_burner_pct,
        thermal_mass_c_per_pct_per_min=thermal_mass,
        response_lag_s=response_lag,
        approach_duration_s=approach_duration_s,
        approach_mean_ror_c_per_min=approach_mean_ror,
        approach_mean_burner_pct=approach_mean_burner_pct,
        final_undershoot_c=final_undershoot,
        timestamp=timestamp
    )


def main():
    """
    Extract thermal metrics from all recent .alog files in roasters directory.
    Write CSV output and print aggregated statistics.
    """
    roasters_dir = Path('/Users/thierrygluzman/Documents/roasters')

    if not roasters_dir.exists():
        print(f"Error: {roasters_dir} does not exist", file=sys.stderr)
        sys.exit(1)

    # Find all .alog files
    alog_files = sorted(roasters_dir.glob('*.alog'), key=os.path.getmtime, reverse=True)

    # Limit to ~40 recent files
    alog_files = alog_files[:40]

    print(f"Processing {len(alog_files)} .alog files...", file=sys.stderr)

    metrics_list = []
    for alog_path in alog_files:
        metrics = compute_thermal_metrics(str(alog_path))
        if metrics:
            metrics_list.append(metrics)
            print(f"✓ {metrics.roast_name[:60]}", file=sys.stderr)
        else:
            print(f"✗ {alog_path.name} (no preheat data)", file=sys.stderr)

    # Write CSV
    output_csv = '/private/tmp/thermal_model_metrics.csv'
    if metrics_list:
        fieldnames = [
            'roast_name', 'ambient_temp', 'ambient_humidity', 'ambient_pressure',
            'ramp_duration_s', 'ramp_mean_ror_c_per_min', 'ramp_mean_burner_pct',
            'thermal_mass_c_per_pct_per_min', 'response_lag_s',
            'approach_duration_s', 'approach_mean_ror_c_per_min', 'approach_mean_burner_pct',
            'final_undershoot_c', 'timestamp'
        ]

        with open(output_csv, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for m in metrics_list:
                writer.writerow({
                    'roast_name': m.roast_name,
                    'ambient_temp': f"{m.ambient_temp:.1f}",
                    'ambient_humidity': f"{m.ambient_humidity:.1f}",
                    'ambient_pressure': f"{m.ambient_pressure:.1f}",
                    'ramp_duration_s': f"{m.ramp_duration_s:.1f}",
                    'ramp_mean_ror_c_per_min': f"{m.ramp_mean_ror_c_per_min:.2f}",
                    'ramp_mean_burner_pct': f"{m.ramp_mean_burner_pct:.1f}",
                    'thermal_mass_c_per_pct_per_min': f"{m.thermal_mass_c_per_pct_per_min:.3f}",
                    'response_lag_s': f"{m.response_lag_s:.1f}",
                    'approach_duration_s': f"{m.approach_duration_s:.1f}",
                    'approach_mean_ror_c_per_min': f"{m.approach_mean_ror_c_per_min:.2f}",
                    'approach_mean_burner_pct': f"{m.approach_mean_burner_pct:.1f}",
                    'final_undershoot_c': f"{m.final_undershoot_c:.2f}",
                    'timestamp': m.timestamp
                })

        print(f"\n✓ CSV written to {output_csv}", file=sys.stderr)

    # Aggregate and print statistics
    if not metrics_list:
        print("No valid preheat data found.", file=sys.stderr)
        return

    print("\n" + "="*70, file=sys.stderr)
    print("THERMAL MODEL AGGREGATION", file=sys.stderr)
    print("="*70, file=sys.stderr)

    # Filter valid samples for aggregation
    valid_thermal_mass = [m.thermal_mass_c_per_pct_per_min for m in metrics_list if m.thermal_mass_c_per_pct_per_min > 0]
    valid_response_lag = [m.response_lag_s for m in metrics_list if m.response_lag_s > 0]
    valid_ramp_ror = [m.ramp_mean_ror_c_per_min for m in metrics_list if m.ramp_mean_ror_c_per_min > 0]
    valid_approach_ror = [m.approach_mean_ror_c_per_min for m in metrics_list if m.approach_mean_ror_c_per_min > 0]

    def mean(lst):
        return sum(lst) / len(lst) if lst else 0

    def stdev(lst):
        if not lst or len(lst) < 2:
            return 0
        m = mean(lst)
        variance = sum((x - m) ** 2 for x in lst) / len(lst)
        return variance ** 0.5

    print(f"\nSamples analyzed: {len(metrics_list)}", file=sys.stderr)
    print(f"\nThermal Mass (°C per % burner power per minute):")
    print(f"  Mean: {mean(valid_thermal_mass):.3f} ± {stdev(valid_thermal_mass):.3f}", file=sys.stderr)
    print(f"  Valid samples: {len(valid_thermal_mass)}", file=sys.stderr)

    print(f"\nResponse Lag (seconds from burner change to temp response):", file=sys.stderr)
    print(f"  Mean: {mean(valid_response_lag):.1f}s ± {stdev(valid_response_lag):.1f}s", file=sys.stderr)
    print(f"  Valid samples: {len(valid_response_lag)}", file=sys.stderr)

    print(f"\nRamp Phase RoR (°C/min):", file=sys.stderr)
    print(f"  Mean: {mean(valid_ramp_ror):.2f} ± {stdev(valid_ramp_ror):.2f}", file=sys.stderr)
    print(f"  Valid samples: {len(valid_ramp_ror)}", file=sys.stderr)

    print(f"\nApproach Phase RoR (°C/min, overshoot-braking zone):", file=sys.stderr)
    print(f"  Mean: {mean(valid_approach_ror):.2f} ± {stdev(valid_approach_ror):.2f}", file=sys.stderr)
    print(f"  Valid samples: {len(valid_approach_ror)}", file=sys.stderr)

    # Ambient sensitivity
    valid_ambient_temps = [m.ambient_temp for m in metrics_list]
    print(f"\nAmbient Conditions (Mean across roasts):", file=sys.stderr)
    print(f"  Temperature: {mean(valid_ambient_temps):.1f}°C ± {stdev(valid_ambient_temps):.1f}°C", file=sys.stderr)
    print(f"  Humidity: {mean([m.ambient_humidity for m in metrics_list]):.1f}% ± {stdev([m.ambient_humidity for m in metrics_list]):.1f}%", file=sys.stderr)
    print(f"  Pressure: {mean([m.ambient_pressure for m in metrics_list]):.1f} hPa", file=sys.stderr)

    # Recommendation for 6-min target preheat
    target_preheat_s = 360  # 6 minutes
    mean_thermal_mass = mean(valid_thermal_mass)
    mean_burner_pct = mean([m.ramp_mean_burner_pct for m in metrics_list])

    if mean_thermal_mass > 0 and mean_burner_pct > 0:
        # ΔT = thermal_mass * burner_pct * time_min
        target_temp_rise = mean_thermal_mass * mean_burner_pct * (target_preheat_s / 60)
        print(f"\nRECOMMENDATION for {target_preheat_s/60:.0f}-minute preheat:", file=sys.stderr)
        print(f"  Expected temperature rise: {target_temp_rise:.1f}°C", file=sys.stderr)
        print(f"  (Assumes mean burner {mean_burner_pct:.0f}% + thermal mass {mean_thermal_mass:.3f})", file=sys.stderr)

    print("\n" + "="*70, file=sys.stderr)


if __name__ == '__main__':
    main()

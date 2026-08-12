#!/usr/bin/env python3
# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.

"""Build a context-bound TilauPID thermal candidate from saved .alog files.

This is intentionally an offline command.  It may inspect a large archive, but
the live START path only reads the resulting small JSON sidecar.
"""

from __future__ import annotations

import argparse
import ast
import math
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

# Allow direct execution from the repository without installing it.
SRC_ROOT = Path(__file__).resolve().parents[2]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from tilauscope.tilaupid_thermal import (
    THERMAL_MODEL_FILENAME,
    ThermalModelCandidate,
    ThermalTrace,
    identify_thermal_model,
    save_candidate,
)


# Absolute burner calibration changed in November 2025. Mixing older,
# doubled values into a physical input/output fit would halve the identified gain.
CALIBRATED_BURNER_EPOCH = 1_761_955_200.0


def _fahrenheit_to_celsius(value: float) -> float:
    return (value - 32.0) * 5.0 / 9.0


def _normalise_identity(value: object) -> str:
    return "".join(ch for ch in str(value or "").casefold() if ch.isalnum())


def _control_channel(value: object) -> str:
    try:
        return "BT" if int(value) in (0, 1) else "ET"
    except (TypeError, ValueError):
        return "BT"


def _load_alog(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_bytes().decode("latin-1")
    value = ast.literal_eval(text)
    if not isinstance(value, dict):
        raise ValueError("profile root is not a dictionary")
    return value


def _burner_channel(data: dict[str, Any]) -> tuple[list[Any], list[Any]] | None:
    timebases = data.get("extratimex", [])
    # The stable sidecar map identifies actuator devices even though
    # Artisan displays their event channel as `{3}` rather than `Burner`.
    name_map = data.get("tilau_name_map") or {}
    for raw_slot, key in name_map.items():
        try:
            slot = int(raw_slot)
        except (TypeError, ValueError):
            continue
        values = data.get("extratemp1", [])
        if (key in {"skywalker_pf", "skycommand_pf"}
                and slot < len(values) and slot < len(timebases)
                and isinstance(values[slot], list)
                and isinstance(timebases[slot], list)):
            return values[slot], timebases[slot]
    for values_key, names_key in (("extratemp1", "extraname1"),
                                  ("extratemp2", "extraname2")):
        names = data.get(names_key, [])
        arrays = data.get(values_key, [])
        for index, name in enumerate(str(item).casefold() for item in names):
            if (("bun" in name or "burn" in name)
                    and index < len(arrays) and index < len(timebases)
                    and isinstance(arrays[index], list)
                    and isinstance(timebases[index], list)):
                return arrays[index], timebases[index]
    return None


def _hold_value(times: list[float], values: list[float], at_sec: float) -> float:
    lo, hi = 0, len(times)
    while lo < hi:
        mid = (lo + hi) // 2
        if times[mid] <= at_sec:
            lo = mid + 1
        else:
            hi = mid
    return values[max(0, lo - 1)]


def _preheat_bounds(data: dict[str, Any], length: int) -> tuple[int, int] | None:
    timeindex = data.get("timeindex", [])
    end = timeindex[0] if timeindex and isinstance(timeindex[0], int) else length - 1
    if end < 0:
        end = length - 1
    start: int | None = None
    event_types = data.get("specialeventstype", [])
    event_names = data.get("specialeventsStrings", [])
    event_indices = data.get("specialevents", [])
    for index, event_type in enumerate(event_types):
        if (event_type == 4 and index < len(event_names) and index < len(event_indices)
                and event_names[index] == "TilauPID Preheat started"
                and isinstance(event_indices[index], int)):
            start = event_indices[index]
            break
    if start is None and data.get("tilau_preheat_sv_c") is not None:
        start = 0
    if start is None or start < 0 or end <= start or end >= length:
        return None
    return start, end


def extract_trace(path: Path) -> tuple[str, str, ThermalTrace] | None:
    """Extract one calibrated, explicitly marked real preheat."""
    try:
        data = _load_alog(path)
    except (OSError, SyntaxError, ValueError):
        return None
    # The cooking-learning exclusion does not apply to the machine's
    # preheat physics. Only simulated traces are rejected here.
    if data.get("tilau_simulated"):
        return None
    epoch = data.get("roastepoch")
    if not isinstance(epoch, (int, float)) or epoch < CALIBRATED_BURNER_EPOCH:
        return None

    machine = _normalise_identity(data.get("roastertype") or data.get("machinesetup"))
    channel = _control_channel(data.get("pidSource", 1))
    mode = str(data.get("mode", "C")).upper()
    times_raw = data.get("timex", [])
    temps_raw = data.get("temp2", []) if channel == "BT" else data.get("temp1", [])
    if not isinstance(times_raw, list) or not isinstance(temps_raw, list):
        return None
    length = min(len(times_raw), len(temps_raw))
    bounds = _preheat_bounds(data, length)
    burner = _burner_channel(data)
    if not machine or bounds is None or burner is None:
        return None
    start, end = bounds
    burner_values_raw, burner_times_raw = burner

    pairs: list[tuple[float, float]] = []
    for t, value in zip(burner_times_raw, burner_values_raw, strict=False):
        if (isinstance(t, (int, float)) and isinstance(value, (int, float))
                and math.isfinite(float(t)) and math.isfinite(float(value))
                and 0.0 <= float(value) <= 100.0):
            pairs.append((float(t), float(value)))
    pairs.sort()
    if len(pairs) < 10:
        return None
    burner_times = [item[0] for item in pairs]
    burner_values = [item[1] for item in pairs]

    observations: list[tuple[float, float, float]] = []
    for index in range(start, end + 1):
        t, raw_temp = times_raw[index], temps_raw[index]
        if (not isinstance(t, (int, float)) or not isinstance(raw_temp, (int, float))
                or raw_temp == -1):
            continue
        time_sec = float(t)
        temp_c = _fahrenheit_to_celsius(float(raw_temp)) if mode == "F" else float(raw_temp)
        if not math.isfinite(time_sec) or not math.isfinite(temp_c) or not -20.0 <= temp_c <= 400.0:
            continue
        observations.append((time_sec, temp_c,
                             _hold_value(burner_times, burner_values, time_sec)))
    if len(observations) < 180:
        return None

    # A centred offline median rejects isolated probe spikes without
    # introducing the two-second phase delay of a trailing real-time filter.
    filtered_temperatures = [
        float(median(row[1] for row in observations[max(0, i - 2):i + 3]))
        for i in range(len(observations))
    ]

    ambient_raw = data.get("ambientTemp", 20.0)
    try:
        ambient = float(ambient_raw)
        if mode == "F":
            ambient = _fahrenheit_to_celsius(ambient)
    except (TypeError, ValueError):
        return None
    t0 = observations[0][0]
    trace = ThermalTrace(
        times_sec=tuple(row[0] - t0 for row in observations),
        temperatures_c=tuple(filtered_temperatures),
        burner_pct=tuple(row[2] for row in observations),
        ambient_c=ambient,
        source=path.name,
    )
    return (machine, channel, trace) if trace.is_valid() else None


def candidate_is_publishable(candidate: ThermalModelCandidate) -> tuple[bool, str]:
    """Offline quality gate; runtime shadow validation is a second, independent gate."""
    if candidate.n_profiles < 3 or candidate.n_samples < 300:
        return False, "insufficient evidence"
    if candidate.derivative_rmse_c_per_sec > 0.18:
        return False, "derivative fit is too inaccurate"
    if candidate.rollout_rmse_c > 8.0 or candidate.cross_validation_rmse_c > 10.0:
        return False, "free-running validation error is too high"
    hold_200 = candidate.equilibrium_power_pct(200.0, 20.0)
    if not 10.0 <= hold_200 <= 80.0:
        return False, f"implausible 200°C holding power ({hold_200:.1f}%)"
    return True, "passed"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("alog_directory", type=Path,
                        help="directory containing the historical .alog files")
    parser.add_argument("--machine", default="",
                        help="machine name/fingerprint; default: most common eligible machine")
    parser.add_argument("--channel", choices=("BT", "ET"), default="BT")
    parser.add_argument("--limit", type=int, default=200,
                        help="maximum newest files to inspect offline (default: 200)")
    parser.add_argument("--output", type=Path,
                        help=f"candidate path (default: ALOG_DIR/{THERMAL_MODEL_FILENAME})")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    directory: Path = args.alog_directory.expanduser().resolve()
    if not directory.is_dir():
        print(f"error: {directory} is not a directory", file=sys.stderr)
        return 2
    files = sorted(directory.glob("*.alog"), key=lambda item: item.stat().st_mtime,
                   reverse=True)[:max(0, args.limit)]
    extracted = [item for path in files if (item := extract_trace(path)) is not None]
    requested_machine = _normalise_identity(args.machine)
    if not requested_machine:
        contexts = Counter((machine, channel) for machine, channel, _trace in extracted
                           if channel == args.channel)
        if not contexts:
            print("error: no eligible marked/calibrated preheat trace", file=sys.stderr)
            return 2
        requested_machine = contexts.most_common(1)[0][0][0]
    traces = [trace for machine, channel, trace in extracted
              if machine == requested_machine and channel == args.channel]
    try:
        candidate = identify_thermal_model(
            traces,
            machine_fingerprint=requested_machine,
            control_channel=args.channel,
            generated_at=datetime.now(UTC).isoformat(),
        )
    except ValueError as exc:
        print(f"error: identification failed: {exc}", file=sys.stderr)
        return 2
    publishable, reason = candidate_is_publishable(candidate)
    print(
        f"model {candidate.fingerprint}: profiles={candidate.n_profiles}, "
        f"samples={candidate.n_samples}, gain={candidate.heating_gain_c_per_sec:.4f}°C/s, "
        f"loss={candidate.cooling_coeff_per_sec:.6f}/s, lag={candidate.response_lag_sec:.1f}s"
    )
    print(
        f"errors: derivative={candidate.derivative_rmse_c_per_sec:.4f}°C/s, "
        f"rollout={candidate.rollout_rmse_c:.2f}°C, "
        f"cross-validation={candidate.cross_validation_rmse_c:.2f}°C"
    )
    if not publishable:
        print(f"error: candidate not published: {reason}", file=sys.stderr)
        return 2
    output = args.output or directory / THERMAL_MODEL_FILENAME
    save_candidate(output, candidate)
    print(f"candidate published for shadow validation: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

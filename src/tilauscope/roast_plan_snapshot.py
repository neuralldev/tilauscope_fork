"""Versioned pre-roast prediction snapshots and out-of-sample errors."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Final

from tilauscope.tilauscope_types import to_agtron


ROAST_PLAN_MODEL_VERSION: Final[str] = "skywalker-v2-p2.1"
ROAST_PLAN_SNAPSHOT_SCHEMA: Final[int] = 1


def _number(value) -> "float | None":
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _time_seconds(value) -> "float | None":
    """Parse the plan's M:SS duration without depending on locale or Qt."""
    if isinstance(value, (int, float)):
        return float(value)
    try:
        minutes, seconds = str(value).strip().split(":", 1)
        return float(minutes) * 60.0 + float(seconds)
    except (AttributeError, TypeError, ValueError):
        return None


def _temperature_c(value, mode: str) -> "float | None":
    number = _number(value)
    if number is None:
        return None
    return (number - 32.0) / 1.8 if mode == "F" else number


def _phase_controls(value) -> "list[float | None]":
    parts = str(value or "").split("|")
    out: list[float | None] = []
    for part in parts[:3]:
        out.append(_number(part.strip().rstrip("%")))
    return out + [None] * (3 - len(out))


def _last_ramp_value(entries, key: str, fallback: "float | None") -> "float | None":
    value = fallback
    for entry in entries or []:
        if isinstance(entry, dict) and _number(entry.get(key)) is not None:
            value = float(entry[key])
    return value


def _source_kinds(sources: dict[str, str]) -> list[str]:
    kinds: set[str] = set()
    for source in sources.values():
        label = str(source or "").lower()
        if "medoid" in label:
            kinds.update(("history", "medoid"))
        elif "blend" in label:
            kinds.update(("grid", "history", "blend"))
        elif "reference" in label:
            kinds.update(("grid", "history"))
        elif "learned" in label or "history" in label:
            kinds.add("history")
        else:
            kinds.add("grid")
    return [kind for kind in ("grid", "history", "blend", "medoid") if kind in kinds]


def build_prediction_snapshot(
        plan: dict, *, plan_id: str, target_color_agtron: float,
        expected_color_basis: str = "ground", mode: str = "C",
        created_at_utc: "str | None" = None) -> dict:
    """Freeze the plan values that exist before the roast starts. """
    heater = _phase_controls(plan.get("Heater (%) (Dry|Mai|Dev)"))
    airflow = _phase_controls(plan.get("Airflow (%) (Dry|Mai|Dev)"))
    sources = {
        "history_profile": str(plan.get("History Profile Source") or "grid"),
        "phase_timing": str(plan.get("Phase Timing Source") or "grid"),
        "first_crack": str(plan.get("FC Temp Source") or "grid"),
        "drop": str(plan.get("Drop Temp Source") or "grid"),
        "heater": str(plan.get("Heater Source") or "grid"),
        "development_profile": str(plan.get("Dev Profile Source") or "grid"),
    }
    milestones = {
        "dry_end": {
            "time_s": _time_seconds(plan.get("Dry Phase")),
            "bt_c": _temperature_c(plan.get("End of Dry Temp"), mode),
        },
        "first_crack": {
            "time_s": _time_seconds(plan.get("FC Time")),
            "bt_c": _temperature_c(plan.get("First Crack Temp"), mode),
        },
        "drop": {
            "time_s": _time_seconds(plan.get("Total Time")),
            "bt_c": _temperature_c(plan.get("Drop Temp"), mode),
        },
    }
    controls = {
        "charge": {"heater_pct": heater[0], "airflow_pct": airflow[0]},
        # Drying controls are held through DE; Maillard changes start after it.
        "dry_end": {"heater_pct": heater[0], "airflow_pct": airflow[0]},
        "first_crack": {
            "heater_pct": _last_ramp_value(plan.get("Heater Ramp"), "heater", heater[1]),
            "airflow_pct": _last_ramp_value(plan.get("Air Ramp"), "airflow", airflow[1]),
        },
        "drop": {
            "heater_pct": _last_ramp_value(plan.get("Dev Ramp"), "heater", heater[2]),
            "airflow_pct": _last_ramp_value(plan.get("Dev Ramp"), "airflow", airflow[2]),
        },
    }
    return {
        "schema_version": ROAST_PLAN_SNAPSHOT_SCHEMA,
        "plan_id": str(plan_id),
        "model_version": ROAST_PLAN_MODEL_VERSION,
        "created_at_utc": created_at_utc or datetime.now(timezone.utc).isoformat(),
        "status": "planned",
        "source_kinds": _source_kinds(sources),
        "sources": sources,
        "predicted": {
            "milestones": milestones,
            "target_color_agtron": round(float(target_color_agtron), 2),
            "expected_color_basis": (expected_color_basis
                                      if expected_color_basis in ("ground", "whole")
                                      else "ground"),
            "controls": controls,
        },
        "actual": {},
        "errors": {},
    }


def complete_prediction_snapshot(snapshot: dict, profile: dict) -> dict:
    """Add observed results without ever changing the frozen prediction."""
    out = copy.deepcopy(snapshot)
    if not out or not isinstance(out.get("predicted"), dict):
        return out
    computed = profile.get("computed") or {}
    mode = str(profile.get("mode") or "C")
    actual_milestones: dict[str, dict[str, float]] = {}
    errors_milestones: dict[str, dict[str, float]] = {}
    for name, time_key, bt_key in (
            ("dry_end", "DRY_time", "DRY_BT"),
            ("first_crack", "FCs_time", "FCs_BT"),
            ("drop", "DROP_time", "DROP_BT")):
        time_s = _number(computed.get(time_key))
        bt_c = _temperature_c(computed.get(bt_key), mode)
        observed: dict[str, float] = {}
        if time_s is not None and time_s > 0.0:
            observed["time_s"] = round(time_s, 3)
        if bt_c is not None and bt_c > 0.0:
            observed["bt_c"] = round(bt_c, 3)
        if observed:
            actual_milestones[name] = observed
        predicted = ((out.get("predicted") or {}).get("milestones") or {}).get(name) or {}
        milestone_errors: dict[str, float] = {}
        if "time_s" in observed and _number(predicted.get("time_s")) is not None:
            milestone_errors["absolute_time_s"] = round(
                abs(observed["time_s"] - float(predicted["time_s"])), 3)
        if "bt_c" in observed and _number(predicted.get("bt_c")) is not None:
            milestone_errors["absolute_bt_c"] = round(
                abs(observed["bt_c"] - float(predicted["bt_c"])), 3)
        if milestone_errors:
            errors_milestones[name] = milestone_errors

    actual_colors: dict[str, float] = {}
    color_errors: dict[str, float] = {}
    target = _number((out.get("predicted") or {}).get("target_color_agtron"))
    color_system = str(profile.get("color_system") or "Agtron")
    for basis, key in (("whole", "whole_color"), ("ground", "ground_color")):
        raw = _number(profile.get(key))
        if raw is None or raw <= 0.0:
            continue
        agtron = round(float(to_agtron(raw, color_system)), 3)
        actual_colors[basis] = agtron
        if target is not None:
            color_errors[basis] = round(abs(agtron - target), 3)

    out["actual"] = {"milestones": actual_milestones, "colors_agtron": actual_colors}
    out["errors"] = {"milestones": errors_milestones, "color_agtron": color_errors}
    out["status"] = "completed" if "drop" in actual_milestones else (
        "observed" if actual_milestones or actual_colors else "planned")
    return out


def summarize_prediction_errors(
        snapshots: "list[dict]", model_version: str = ROAST_PLAN_MODEL_VERSION) -> dict:
    """Return version-isolated MAE from genuinely pre-roast snapshots."""
    samples: dict[str, list[float]] = {}
    contributing_ids: set[str] = set()
    for snapshot in snapshots:
        if (not snapshot.get("plan_id")
                or snapshot.get("model_version") != model_version):
            continue
        plan_id = str(snapshot["plan_id"])
        if plan_id in contributing_ids:
            continue
        errors = snapshot.get("errors") or {}
        contributed = False
        for milestone, values in (errors.get("milestones") or {}).items():
            for measure, value in values.items():
                number = _number(value)
                if number is not None:
                    samples.setdefault(f"{milestone}.{measure}", []).append(number)
                    contributed = True
        for basis, value in (errors.get("color_agtron") or {}).items():
            number = _number(value)
            if number is not None:
                samples.setdefault(f"color_agtron.{basis}", []).append(number)
                contributed = True
        if contributed:
            contributing_ids.add(plan_id)
    metrics = {
        metric: {"n": len(values), "mae": round(sum(values) / len(values), 3)}
        for metric, values in sorted(samples.items()) if values
    }
    return ({"model_version": model_version,
             "snapshot_count": len(contributing_ids),
             "metrics": metrics} if metrics else {})

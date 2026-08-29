# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.

"""Durable, machine-bound evidence for PID calibration.

The live protocol remains in :mod:`tilauscope.pid_calibration`.  This module is
the filesystem boundary: it gives a qualification an exact machine/actuator
identity and writes audit evidence atomically.  Persisted zero-output evidence
is historical proof only; a new application session must qualify 0% again.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from tilauscope.pid_calibration import (
    CalibrationAuditEvent,
    verify_calibration_audit,
)


_SCHEMA_VERSION = 1


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256(payload: object) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


@dataclass(frozen=True, slots=True)
class CalibrationMachineIdentity:
    """Stable identity of both the roaster and its exact control path."""

    roaster_id: str
    display_name: str
    temperature_unit: str
    pid_source: int
    heater_slider: int
    actuator_signature: str

    @property
    def fingerprint(self) -> str:
        return _sha256(asdict(self))


def build_machine_identity(
    *,
    roaster_id: str | None,
    display_name: str,
    temperature_unit: str,
    pid_source: int,
    heater_slider: int,
    action_id: int,
    action_command: str,
    slider_min: int,
    slider_max: int,
    slider_factor: float,
    slider_offset: float,
    inverted: bool,
) -> CalibrationMachineIdentity | None:
    """Return a fail-closed identity without retaining a possibly secret command."""
    stable_id = str(roaster_id or "").strip().lower()
    if not stable_id or not display_name.strip():
        return None
    unit = temperature_unit.strip().upper()
    if unit not in {"C", "F"}:
        return None
    if heater_slider not in range(4) or action_id <= 0:
        return None
    if slider_max <= slider_min or slider_factor <= 0 or inverted:
        return None
    actuator_signature = _sha256({
        "action_command": str(action_command),
        "action_id": int(action_id),
        "slider_factor": float(slider_factor),
        "slider_max": int(slider_max),
        "slider_min": int(slider_min),
        "slider_offset": float(slider_offset),
    })
    return CalibrationMachineIdentity(
        roaster_id=stable_id,
        display_name=display_name.strip(),
        temperature_unit=unit,
        pid_source=int(pid_source),
        heater_slider=heater_slider,
        actuator_signature=actuator_signature,
    )


def _atomic_json_write(path: Path, payload: dict[str, Any]) -> Path:
    """Flush a private temporary file, then atomically replace *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(
                payload,
                stream,
                allow_nan=False,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
        return path
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise


def write_zero_qualification_evidence(
    directory: Path,
    identity: CalibrationMachineIdentity,
    *,
    qualified_at_utc: str | None = None,
) -> Path:
    """Persist proof of a 0% test, without authorising reuse in another session."""
    payload: dict[str, Any] = {
        "schema": _SCHEMA_VERSION,
        "kind": "zero_output_qualification",
        "qualified_at_utc": qualified_at_utc or datetime.now(UTC).isoformat(),
        "identity": asdict(identity),
        "identity_fingerprint": identity.fingerprint,
        "reusable_authorization": False,
    }
    payload["evidence_hash"] = _sha256(payload)
    path = directory / f"zero-output-{identity.fingerprint}.json"
    return _atomic_json_write(path, payload)


def write_hardware_pilot_manifest(
    directory: Path,
    identity: CalibrationMachineIdentity,
    *,
    generated_at_utc: str | None = None,
) -> Path:
    """Export the exact, non-authorising control path for a supervised pilot."""
    payload: dict[str, Any] = {
        "schema": _SCHEMA_VERSION,
        "kind": "pid_hardware_pilot_manifest",
        "protocol": "pid-autocalibration-600s-v1",
        "generated_at_utc": generated_at_utc or datetime.now(UTC).isoformat(),
        "identity": asdict(identity),
        "identity_fingerprint": identity.fingerprint,
        "authorization_status": "pending_supervised_physical_pilot",
        "authorizes_heat": False,
        "required_evidence": [
            "physical_zero_confirmed",
            "positive_actuator_direction_confirmed",
            "all_runtime_interlocks_exercised",
            "final_audit_journal_verified",
            "operator_and_reviewer_signoff",
        ],
    }
    payload["manifest_hash"] = _sha256(payload)
    path = directory / f"pilot-{identity.fingerprint}.json"
    return _atomic_json_write(path, payload)


def verify_hardware_pilot_manifest(path: Path) -> bool:
    """Verify that a pilot sheet is intact and explicitly non-authorising."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        manifest_hash = payload.pop("manifest_hash")
        if manifest_hash != _sha256(payload):
            return False
        identity = CalibrationMachineIdentity(**payload["identity"])
        return bool(
            payload["kind"] == "pid_hardware_pilot_manifest"
            and payload["identity_fingerprint"] == identity.fingerprint
            and payload["authorization_status"]
            == "pending_supervised_physical_pilot"
            and payload["authorizes_heat"] is False
        )
    except (KeyError, TypeError, ValueError, OSError):
        return False


def write_calibration_journal(
    path: Path,
    *,
    identity: CalibrationMachineIdentity,
    events: tuple[CalibrationAuditEvent, ...],
    outcome: Literal["complete", "refused", "safe_stop"],
    reason: str | None,
    created_at_utc: str | None = None,
) -> Path:
    """Atomically export a complete audit only when its hash chain is valid."""
    if not events or not verify_calibration_audit(events):
        raise ValueError("invalid calibration audit chain")
    payload: dict[str, Any] = {
        "schema": _SCHEMA_VERSION,
        "protocol": "pid-autocalibration-600s-v1",
        "created_at_utc": created_at_utc or datetime.now(UTC).isoformat(),
        "identity": asdict(identity),
        "identity_fingerprint": identity.fingerprint,
        "outcome": outcome,
        "reason": reason,
        "terminal_event_hash": events[-1].event_hash,
        "events": [asdict(event) for event in events],
    }
    payload["journal_hash"] = _sha256(payload)
    return _atomic_json_write(path, payload)


def verify_calibration_journal(path: Path) -> bool:
    """Verify metadata, machine fingerprint, journal hash and event hash chain."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        journal_hash = payload.pop("journal_hash")
        if not isinstance(journal_hash, str) or journal_hash != _sha256(payload):
            return False
        identity = CalibrationMachineIdentity(**payload["identity"])
        if payload["identity_fingerprint"] != identity.fingerprint:
            return False
        events = tuple(
            CalibrationAuditEvent(**event) for event in payload["events"]
        )
        return (
            bool(events)
            and payload["terminal_event_hash"] == events[-1].event_hash
            and verify_calibration_audit(events)
        )
    except (KeyError, TypeError, ValueError, OSError):
        return False

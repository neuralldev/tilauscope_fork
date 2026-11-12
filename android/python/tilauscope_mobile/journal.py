# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""Append-only JSON-lines journal of one recording, and its recovery.

Every line is flushed (survives process death); fsync is bounded in time and
forced on milestones and stop (survives power loss up to the last sync).
"""

import json
import os
from pathlib import Path
import time

from .session import Reading, Session

FORMAT = "tilauscope-mobile-journal"
FSYNC_EVERY_S = 5.0
AMBIENT_KEYS = ("temperature_c", "humidity_pct", "pressure_hpa")


class Journal:
    def __init__(self, path: str, *, simulated: bool, uuid: str = "", epoch: float | None = None,
                 tz_offset: int = 0, title: str = "", beans: str = "", greens: dict | None = None) -> None:
        self._stream = open(path, "w", encoding="utf-8")
        self._synced_at = time.monotonic()
        self._write({"format": FORMAT, "schema_version": 1, "simulated": simulated,
                     "uuid": uuid, "epoch": epoch, "tz_offset": tz_offset,
                     "title": title, "beans": beans, "greens": greens}, sync=True)

    def _write(self, event: dict, *, sync: bool = False) -> None:
        self._stream.write(json.dumps(event, allow_nan=False) + "\n")
        self._stream.flush()
        if sync or time.monotonic() - self._synced_at >= FSYNC_EVERY_S:
            os.fsync(self._stream.fileno())
            self._synced_at = time.monotonic()

    def sample(self, elapsed_s: float, reading: Reading, extras: dict | None = None) -> None:
        event = {"event": "sample", "t": elapsed_s, "bt": reading.bt_c, "et": reading.et_c}
        if extras:
            event["x"] = extras
        self._write(event)

    def mark(self, milestone: str, elapsed_s: float, index: int) -> None:
        self._write({"event": "mark", "milestone": milestone, "t": elapsed_s, "index": index},
                    sync=True)

    def setting(self, lever: str, value: int, elapsed_s: float, by: str | int | None = None) -> None:
        """`by`: "pid" for TilauPID, an alarm's number, None for the operator."""
        event = {"event": "setting", "lever": lever, "value": value, "t": elapsed_s}
        if by is not None:
            event["by"] = by
        self._write(event)

    def preheat(self, target_c: float | None, pid_source: int, elapsed_s: float) -> None:
        self._write({"event": "preheat", "target_c": target_c, "pid_source": pid_source, "t": elapsed_s})

    def ambient(self, values: dict, elapsed_s: float) -> None:
        self._write({"event": "ambient", "t": elapsed_s, **values})

    def weight(self, kind: str, grams: int, elapsed_s: float) -> None:
        self._write({"event": "weight", "kind": kind, "grams": grams, "t": elapsed_s}, sync=True)

    def unmark(self, milestone: str, elapsed_s: float) -> None:
        self._write({"event": "unmark", "milestone": milestone, "t": elapsed_s}, sync=True)

    def stop(self, elapsed_s: float) -> None:
        self._write({"event": "stop", "t": elapsed_s}, sync=True)
        self.close()

    def close(self) -> None:
        self._stream.close()


def append_after_stop(path: str, event: dict) -> None:
    """Roasted weight and colours come after the stop line, once the journal is closed."""
    with open(path, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def recover(path: str) -> tuple[Session, bool]:
    """Replay a journal; return the session (always stopped) and whether it was interrupted.

    A truncated last line is the expected trace of a crash and is ignored; any
    other unreadable line raises ValueError.
    """
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    events = []
    for number, line in enumerate(lines):
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            if number != len(lines) - 1:
                raise ValueError(f"Unreadable journal line {number + 1}") from None
    if not events or events[0].get("format") != FORMAT or events[0].get("schema_version") != 1:
        raise ValueError("Not a version 1 mobile journal")
    session = Session(simulated=bool(events[0].get("simulated")))
    session.uuid = str(events[0].get("uuid") or "")
    session.started_epoch = events[0].get("epoch")
    session.tz_offset = int(events[0].get("tz_offset") or 0)
    session.title = str(events[0].get("title") or "")
    session.beans = str(events[0].get("beans") or "")
    session.greens = events[0].get("greens")
    session.start(0)
    last = 0.0
    stopped = False
    try:
        for event in events[1:]:
            kind, last = event["event"], event["t"]
            if kind == "weight":
                if event["kind"] == "roasted" and not stopped:
                    raise ValueError("A roasted weight comes after the stop")
                session.set_weight(event["kind"], event["grams"])
            elif kind == "colour":
                session.set_colour(event["kind"], event["value"])
            elif kind == "exported" and stopped:
                session.exported = str(event["name"])
            elif stopped:
                raise ValueError("Only weights follow the stop")
            elif kind == "sample":
                session.ingest(Reading(event["bt"], event["et"]), last, event.get("x"))
            elif kind == "mark":
                session.mark(event["milestone"], last, event["index"]) # where it was marked, found back in the curve too
                if session.milestones[event["milestone"]] != event["index"]:
                    raise ValueError("Milestone index does not match the replayed samples")
            elif kind == "setting":
                session.record_setting(event["lever"], event["value"], last)
                by = event.get("by")
                if by == "pid":
                    session.pid_settings.add(len(session.settings) - 1)
                elif by is not None:
                    session.alarm_settings[len(session.settings) - 1] = int(by)
            elif kind == "preheat":
                session.preheat_sv_c, session.pid_source = event["target_c"], int(event["pid_source"])
            elif kind == "ambient":
                session.ambient = {key: event[key] for key in AMBIENT_KEYS if key in event}
            elif kind == "unmark":
                session.unmark(event["milestone"])
            elif kind == "stop":
                session.stop(last)
                stopped = True
            else:
                raise ValueError(f"Unknown journal event {kind!r}")
    except (KeyError, TypeError) as error:
        raise ValueError("Malformed journal event") from error
    if stopped:
        return session, False
    session.stop(last) # interrupted: read-only, never resumed
    return session, True

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""MQTT sensors (MQTT-SPEC): the broker and its sensors as configured, and the value a message
carries, scaled as the desktop scales it (tilauscope/mqttbridge.py, _scale_reading)."""

import json
import math

# What a sensor feeds: the room readings the tablet records, and the power of the energy session.
FEEDS = ("room_c", "room_rh", "pressure_hpa", "roaster_w", "extractor_w")
ROOM_KEYS = {"room_c": "temperature_c", "room_rh": "humidity_pct", "pressure_hpa": "pressure_hpa"}
MAX_TEXT = 200


def _text(value, what: str, limit: int = MAX_TEXT, required: bool = True) -> str:
    text = str(value or "").strip()
    if (required and not text) or len(text) > limit:
        raise ValueError(f"MQTT: {what} is missing or too long")
    return text


def _factor(value, what: str) -> float:
    number = float(1.0 if value in (None, "") else value)
    if not math.isfinite(number) or number == 0:
        raise ValueError(f"MQTT: {what} must be a number other than 0")
    return number


def validate(data: dict) -> dict:
    """A clean copy of the broker and its sensors, or ValueError naming the first problem."""
    if not isinstance(data, dict):
        raise ValueError("MQTT: the broker must be an object")
    port = data.get("port", 1883)
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("MQTT: the port is between 1 and 65535")
    sensors = [sensor(item) for item in data.get("sensors") or []]
    return {"host": _text(data.get("host"), "the host", 253), "port": port,
            "user": _text(data.get("user"), "the user", 64, required=False),
            "password": str(data.get("password") or "")[:MAX_TEXT],
            "tls": bool(data.get("tls", False)), "sensors": sensors}


def sensor(data: dict) -> dict:
    """A clean copy of one sensor, or ValueError naming the first problem."""
    if not isinstance(data, dict) or data.get("feeds") not in FEEDS:
        raise ValueError("MQTT: a sensor feeds a room reading or a power")
    topic = _text(data.get("topic"), "a topic")
    if "+" in topic or "#" in topic:
        raise ValueError("MQTT: a sensor reads one topic, without + or #")
    unit = ("F" if data.get("unit") == "F" else "C") if data["feeds"] == "room_c" else ""
    return {"name": _text(data.get("name"), "a name", 24), "topic": topic,
            "field": _text(data.get("field"), "a field", 64, required=False),
            "feeds": data["feeds"], "unit": unit,
            "multiplier": _factor(data.get("multiplier"), "the multiplier"),
            "divider": _factor(data.get("divider"), "the divider")}


def reading(sensor: dict, payload: str) -> float | None:
    """The sensor's value in a message: its field (else "value") of a JSON object, or the payload
    itself; times the multiplier, over the divider; a °F room temperature in °C. None when the
    message does not carry a number."""
    try:
        data = json.loads(payload)
    except ValueError:
        data = payload
    try:
        raw = data[sensor["field"] or "value"] if isinstance(data, dict) else data
        value = float(raw) * sensor["multiplier"] / sensor["divider"]
    except (KeyError, TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return (value - 32) * 5 / 9 if sensor["unit"] == "F" else value

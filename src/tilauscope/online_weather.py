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

"""The room as the online weather sees it, for a setup with no ambient probe.

Called only after the operator has agreed to it (tilau_privacy_ui.ensure_geo_consent):
the location comes from the internet address.
"""

from __future__ import annotations

import requests
from PyQt6.QtCore import QT_TRANSLATE_NOOP
from PyQt6.QtWidgets import QApplication


def fetch_online_weather() -> dict:
    """Location, current weather and ground altitude, as plain data. Worker thread.

    Touches no widget and no ``qmc``: only the returned dict crosses back.
    """
    geo_res = requests.get("http://ip-api.com/json/", timeout=5)
    geo_res.raise_for_status()
    geo_data = geo_res.json()

    lat = geo_data.get("lat")
    lon = geo_data.get("lon")
    if lat is None or lon is None:
        # Declared here, translated at display: this runs off the GUI thread
        # and returns data only, so the catalogue is read by the slot.
        raise ValueError(QT_TRANSLATE_NOOP(
            "tilauscope_beancave", "Could not detect location."))

    # Without an `elevation` parameter Open-Meteo answers with the terrain
    # height of the place, which is the altitude the plan corrects for.
    w_res = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,surface_pressure",
        },
        timeout=5)
    w_res.raise_for_status()
    w_data = w_res.json()
    current = w_data.get("current", {})
    return {
        "city": geo_data.get("city", ""),
        "temperature": current.get("temperature_2m"),
        "humidity": current.get("relative_humidity_2m"),
        "pressure": current.get("surface_pressure"),
        "elevation": w_data.get("elevation"),
    }


def weather_error_text(message: str) -> str:
    """A lookup failure in the operator's language. GUI thread.

    The failures this module raises are declared above with QT_TRANSLATE_NOOP;
    a network error carries no translation and passes through unchanged.
    """
    return QApplication.translate("tilauscope_beancave", message) if message else ""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2025-2026 Tilau
# This file is part of TilauScope.

"""The operator's Artisan settings, read by BeanCave alone.

Artisan writes its settings when it quits or on Save settings: what is read here
is the state of that moment. BeanCave alone takes the unit, the rate-of-rise
settings, the event sliders and the roasts folder from it, so its curves read like
Artisan's.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QSettings

#: Artisan's names (artisanlib/util.py): the domain locates the file on macOS, the name elsewhere.
_ORGANIZATION, _DOMAIN, _APPLICATION = 'artisan-scope', 'artisan-scope.org', 'Artisan'


def artisan_settings() -> QSettings | None:
    """The operator's Artisan settings, or None when Artisan never saved any."""
    settings = QSettings(QSettings.Format.NativeFormat, QSettings.Scope.UserScope,
                         _DOMAIN if sys.platform == 'darwin' else _ORGANIZATION, _APPLICATION)
    return settings if settings.contains('Mode') else None


def roasts_folder(settings: QSettings | None) -> str:
    """Where Artisan saves roasts: its autosave folder, else its profiles folder."""
    if settings is None:
        return ''
    for key in ('autosavepath', 'profilepath'):
        folder = str(settings.value(key, '') or '')
        if folder and Path(folder).is_dir():
            return folder
    return ''


def _int(settings: QSettings, key: str, default: int) -> int:
    try:
        return int(settings.value(key, default))
    except (TypeError, ValueError):
        return default


def _bool(settings: QSettings, key: str, default: bool) -> bool:
    value: Any = settings.value(key, default)
    return value.lower() == 'true' if isinstance(value, str) else bool(value)


def _strings(settings: QSettings, key: str, default: list) -> list:
    value = settings.value(key, None)
    return [str(v) for v in value] if isinstance(value, (list, tuple)) and len(value) == len(default) else default


def apply_artisan_settings(window: Any, settings: QSettings | None) -> None:
    """Give the stand-in window the unit, RoR and slider settings of the operator's Artisan."""
    if settings is None:
        return
    qmc = window.qmc
    qmc.mode = 'F' if str(settings.value('Mode', qmc.mode)) == 'F' else 'C'
    qmc.curvefilter = _int(settings, 'curvefilter', qmc.curvefilter)
    qmc.interpolateDropsflag = _bool(settings, 'interpolateDropsflag', qmc.interpolateDropsflag)
    qmc.filterDropOuts = _bool(settings, 'filterDropOuts', qmc.filterDropOuts)
    qmc.deltaBTfilter = _int(settings, 'RoC/deltafilter', qmc.deltaBTfilter)
    qmc.deltaETfilter = _int(settings, 'RoC/deltaETfilter', qmc.deltaETfilter)
    qmc.deltaBTspan = _int(settings, 'RoC/DeltaSpan', qmc.deltaBTspan)
    qmc.deltaETspan = _int(settings, 'RoC/DeltaETspan', qmc.deltaETspan)
    qmc.RoRlimitFlag = _bool(settings, 'RoRlimits/RoRlimitFlag', qmc.RoRlimitFlag)
    qmc.RoRlimit = _int(settings, 'RoRlimits/RoRlimit', qmc.RoRlimit)
    qmc.RoRlimitm = _int(settings, 'RoRlimits/RoRlimitm', qmc.RoRlimitm)
    # An event Artisan left unnamed keeps Artisan's own default name: a lane needs one.
    qmc.etypes = [name or default for name, default in zip(_strings(settings, 'events/etypes', qmc.etypes), qmc.etypes, strict=True)]
    qmc.EvalueColor = _strings(settings, 'events/EvalueColor', qmc.EvalueColor)
    visible = settings.value('Sliders/slidervisibilities', None)
    if isinstance(visible, (list, tuple)) and len(visible) == len(window.eventslidervisibilities):
        window.eventslidervisibilities = [int(v) for v in visible]

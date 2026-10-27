# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2025-2026 Tilau
# This file is part of TilauScope.

"""What a roast says of its coffee, shared by both apps: the proposed title and
the beans text, whose `uuid:` line links the roast to its BeanCave record.

Labels are English source text with their translation context, marked for the
desktop's translation tools; `translate(context, text)` renders them (the
desktop passes QApplication.translate, the tablet keeps the English).
"""

from __future__ import annotations

from typing import Callable

from tilaucore.bean_qualifiers import QT_TRANSLATE_NOOP
from tilaucore.beans import GreenBean

_FARM = QT_TRANSLATE_NOOP("tilauscope_common", "Farm:")
_PROCESS = QT_TRANSLATE_NOOP("tilauscope_common", "Process")
_VARIETY = QT_TRANSLATE_NOOP("tilauscope_common", "Variety")
_ALTITUDE = QT_TRANSLATE_NOOP("tilauscope_common", "Altitude:")
_SCA = QT_TRANSLATE_NOOP("tilauscope_common", "SCA: {0}")


def _english(context: str, text: str) -> str:  # noqa: ARG001
    return text


def roast_title(bean: GreenBean) -> str:
    """The title proposed for a roast of this coffee: name - process - crop."""
    crop = str(bean.crop) if bean.crop else 'N/A'
    return f"{bean.name} - {bean.process} - {crop}"


def beans_text(bean: GreenBean, translate: Callable[[str, str], str] = _english) -> str:
    """The beans text of a roast of this coffee, one fact per line."""
    parts: list[str] = []
    if bean.name:
        parts.append(bean.name)
    if bean.country:
        parts.append(bean.country)
    if bean.farm:
        parts.append("{0} {1}".format(translate(*_FARM), bean.farm))
    if bean.process:
        parts.append("{0} {1}".format(translate(*_PROCESS), bean.process))
    if bean.varieties:
        parts.append("{0} {1}".format(translate(*_VARIETY), bean.varieties))
    if bean.altitude:
        parts.append("{0} {1}m".format(translate(*_ALTITUDE), bean.altitude))
    if bean.sca:
        parts.append(translate(*_SCA).format(f"{bean.sca:.1f}"))
    if bean.uuid:
        # Machine key, not a label: the desktop reads it back to find the bean.
        # Translated, French returned "uuid : : {0}" and the roast lost its link.
        parts.append(f"uuid: {bean.uuid}")
    return "\n".join(parts)

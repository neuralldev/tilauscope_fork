#
# ABOUT
# tilau_privacy.py - one scrubber for everything that leaves the machine

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

"""Personal-data scrubbing for anything that leaves the user's machine.

Two destinations, one rule table, two profiles:

``Profile.DIAGNOSTIC``
    The debug archive attached to a public issue. Nothing there needs a
    reachable address, so every URL is destroyed outright.

``Profile.AI_OUTBOUND``
    A prompt sent to a third-party model. The bean extractor *needs* its URL —
    destroying it would destroy the feature — so URLs are normalised instead:
    credentials, fragment, tracking and identifying query parameters removed,
    private hosts refused. Everything else is scrubbed harder than in a log,
    because a prompt can carry a free-text note the user typed.

This is a last line of defence, not a personal-data classifier. A caller that
knows a field is personal must not put it in the payload in the first place.
"""
from __future__ import annotations

import logging
import platform
from pathlib import Path
from typing import Final

# The rules and the scrubbers are the shared core's (the tablets publish with them too); re-exported for the desktop.
from tilaucore.privacy import (  # noqa: F401
    _LOCAL_SUFFIXES, REDACTION, Profile, RedactionReport, UrlVerdict, host_is_public, sanitize_log_text,
    sanitize_text, sanitize_url,
)

_log: Final[logging.Logger] = logging.getLogger(__name__)


def runtime_sensitive_values() -> tuple[str, ...]:
    """Local identity values that must never leave the machine.

    Read fresh on every call: the operator may be set in Settings between two
    requests, and this is never on a hot path.
    """
    values: set[str] = {Path.home().name, platform.node()}
    try:
        from PyQt6.QtCore import QSettings  # noqa: PLC0415
        settings = QSettings()
        values.update(
            str(settings.value(key, '') or '').strip() for key in (
                'operator', 'operator_setup', 'organization', 'organization_setup')
        )
    except Exception:  # noqa: BLE001 - headless tooling has no Qt settings
        pass
    # Very short values create destructive false positives (an operator initial
    # such as "T"), while paths and labelled fields stay covered by the
    # structural rules.
    return tuple(sorted((value for value in values if len(value) >= 3),
                        key=len, reverse=True))


MAX_PROMPT_CHARS: Final[int] = 32_000

_TRUNCATION_NOTE: Final[str] = '\n\n[…truncated by TilauScope before sending…]'


def _cap(text: str, limit: int, report: RedactionReport) -> str:
    if len(text) <= limit:
        return text
    report.truncated_chars += len(text) - limit
    return text[:limit] + _TRUNCATION_NOTE


def prepare_ai_messages(system_prompt: str,
                        user_content: str,
                        *,
                        task: str = '',
                        limit: int = MAX_PROMPT_CHARS,
                        ) -> tuple[list[dict[str, str]], RedactionReport]:
    """Build the message list for a model request, scrubbed and capped.

    Every AI call site in TilauScope goes through here — the system prompt too,
    because ours interpolate runtime values such as the roaster's name. Returns
    the messages and a report of what was taken out, which the caller logs and
    may show before sending.
    """
    report = RedactionReport()
    known  = runtime_sensitive_values()

    system = sanitize_text(system_prompt, known,
                           profile=Profile.AI_OUTBOUND, report=report)
    user   = sanitize_text(user_content, known,
                           profile=Profile.AI_OUTBOUND, report=report)
    user   = _cap(user, limit, report)

    if not report.is_clean:
        _log.info('AI payload sanitized%s: %s',
                  f' for {task}' if task else '', report.summary())

    return ([{'role': 'system', 'content': system},
             {'role': 'user',   'content': user}], report)

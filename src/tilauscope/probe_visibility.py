"""ET display availability, derived from the roaster declarations."""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Any

from tilauscope.roasters import RoasterManager, roast_context_for


def valid_temperature(value: Any) -> bool:
    """Artisan's missing reading is -1; zero is a valid temperature."""
    return (isinstance(value, (int, float)) and value != -1
            and math.isfinite(value))


@lru_cache(maxsize=64)
def _declared_et(name: str) -> bool | None:
    context = RoasterManager(name).get_roast_context()
    return getattr(context, 'has_et_probe', None)


def et_available_in_profile(data: Any) -> bool:
    """Historical views use the recorded machine and its own measurements."""
    name = str(data.get('roastertype', '') or '')
    if name and _declared_et(name) is False:
        return False
    return any(valid_temperature(value) for value in data.get('temp1', ()))


def et_available_for(aw: Any) -> bool:
    """The selected roaster's ET flag, resolved once per roaster selection."""
    roast_context_for(aw)
    return bool(getattr(aw, '_tilau_has_et', True))

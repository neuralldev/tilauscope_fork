# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.

"""The preheat's sensor safety, from the library shared with the Android tablet."""

from tilaucore.preheat_safety import *  # noqa: F403  (the desktop keeps importing tilauscope.tilaupid_safety)
from tilaucore.preheat_safety import PreheatSensorGuard, SensorSafetyDecision, SensorSafetyLimits  # noqa: F401

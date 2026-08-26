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

"""The roasting window, taken a slice at a time.

TilauScope is one widget with one set of attributes; these modules are slices of
it, not collaborators that own anything. Each is a mixin over QWidget, and the
window assembles them.

Alongside the mixins: ``parts`` and ``sidebar`` hold the widgets that do read the
running Artisan session — unlike ``tilauscope.widgets``, which knows nothing of
it — and ``layout`` holds the fixed geometry they are laid out against.
"""

from __future__ import annotations

from tilauscope.window.build import BuildMixin
from tilauscope.window.chrome import ChromeMixin
from tilauscope.window.emergency import EmergencyMixin
from tilauscope.window.lifecycle import LifecycleMixin
from tilauscope.window.live import LiveMixin
from tilauscope.window.milestones import MilestonesMixin
from tilauscope.window.sliders import SlidersMixin

__all__ = ['BuildMixin', 'ChromeMixin', 'EmergencyMixin', 'LifecycleMixin', 'LiveMixin',
           'MilestonesMixin', 'SlidersMixin']

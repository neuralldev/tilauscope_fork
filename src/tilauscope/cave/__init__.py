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

"""BeanCave, taken a slice at a time.

BeanCave is one dialog with one set of attributes; the mixins here are slices of
it, not collaborators that own anything. Each is a mixin over QDialog, and the
dialog assembles them.

Alongside the mixins: ``widgets`` holds the self-contained widgets its screens
are built from, ``workers`` the background jobs it runs off the GUI thread, and
``common`` the constants, glyphs and helpers all three read.
"""

from tilauscope.cave.ambient import AmbientMixin
from tilauscope.cave.analysis import AnalysisMixin
from tilauscope.cave.bean_tab import BeanTabMixin
from tilauscope.cave.bean_tab_build import BeanTabBuildMixin
from tilauscope.cave.lifecycle import LifecycleMixin
from tilauscope.cave.plan_tab import PlanTabMixin
from tilauscope.cave.printing import PrintingMixin
from tilauscope.cave.viewer import ViewerMixin
from tilauscope.cave.viewer_multi import ViewerMultiMixin
from tilauscope.cave.viewer_plot import ViewerPlotMixin

__all__ = ['AmbientMixin', 'AnalysisMixin', 'BeanTabBuildMixin', 'BeanTabMixin', 'LifecycleMixin', 'PlanTabMixin',
           'PrintingMixin', 'ViewerMixin', 'ViewerMultiMixin', 'ViewerPlotMixin']

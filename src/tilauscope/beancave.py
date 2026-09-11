#
# ABOUT
# Beancave

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
# TiLau 2025

# Simple green-bean cave: JSON list of beans linked to roasts by name, with stock in
# grams consumed from roast properties. Printer support credit: github.com/AndBondStyle/niimprint.

from __future__ import annotations

from PyQt6.QtWidgets import QDialog

from tilauscope.cave import (AmbientMixin, AnalysisMixin, BeanTabBuildMixin, BeanTabMixin, LifecycleMixin,
                             PlanTabMixin, PrintingMixin, ViewerMixin, ViewerMultiMixin,
                             ViewerPlotMixin)


class BeancaveDlg(LifecycleMixin, PlanTabMixin, ViewerMixin, ViewerMultiMixin, ViewerPlotMixin,
                  AnalysisMixin, BeanTabMixin, BeanTabBuildMixin, AmbientMixin, PrintingMixin,
                  QDialog): # 2025-12-23 changed from ArtisanResizeablDialog to QDialog to handle modality
    """The bean library, the roast viewer and the roast plan, in one dialog.

    The dialog itself is only the assembly: every slice of behaviour lives in a
    mixin under ``tilauscope.cave``, and they all share this one set of
    attributes. QDialog comes last so the mixins can override its handlers.
    """

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

"""Widgets with no knowledge of Artisan, roasting or the window that hosts them.

Everything here was written inside displayscope.py because that is the file that
happened to need it first, which is also why nothing else could use it. Each of
these takes its values as arguments and reports back through a signal or a
callback; none of them reads ``aw`` or the roasting state.
"""

from __future__ import annotations

from tilauscope.widgets.flow_layout import FlowLayout
from tilauscope.widgets.labels import TickerLabel, ClickableLabel
from tilauscope.widgets.controls import SmartRoller, ClickableValue, HoldToFireButton
from tilauscope.widgets.readouts import ExtraCounterWidget, LCDReadout
from tilauscope.widgets.phase import PhaseWidget
from tilauscope.widgets.badges import EventFiredBadge
from tilauscope.widgets.dialogs import PlaybackWarningDlg

__all__ = [
    'ClickableLabel',
    'ClickableValue',
    'EventFiredBadge',
    'ExtraCounterWidget',
    'FlowLayout',
    'HoldToFireButton',
    'LCDReadout',
    'PhaseWidget',
    'PlaybackWarningDlg',
    'SmartRoller',
    'TickerLabel',
]

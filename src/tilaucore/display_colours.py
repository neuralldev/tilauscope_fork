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
# Tilau 2025-2026

"""The colours a roast is drawn in, shared by both apps: those of the TilauScope
theme (includes/Themes/TilauScope/Catppuccin.athm). The desktop lets the operator
change them in Artisan's palette; the tablet draws with these."""

# One hue per probe; a rate wears its probe's hue one step back
# (the desktop's dimmed(), checked by test_display_colours).
COLOR_GRAIN = '#89B4FA'       # blue — grain temperature
COLOR_AIR = '#FAB387'         # peach — air temperature
COLOR_GRAIN_RISE = '#457ed9'  # grain rate of rise
COLOR_AIR_RISE = '#d97a43'    # air rate of rise

# The settings sliders and lanes, by lever: the theme's event colours (EvalueColor),
# in Artisan's event order air, drum, extractor, burner.
LEVER_COLOURS: dict[str, str] = {'air': '#0096ff', 'drum': '#008f00', 'extractor': '#ffd479', 'burner': '#ff2600'}

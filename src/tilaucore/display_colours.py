# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2025-2026 Tilau
# This file is part of TilauScope.

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

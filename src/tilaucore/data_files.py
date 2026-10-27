# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2025-2026 Tilau
# This file is part of TilauScope.

"""The data files of the shared library, found here by both apps."""

from pathlib import Path

# Each named from this file, so the desktop's doctrine test checks it is really there.
ROASTERS_JSON = Path(__file__).parent / "data/roasters.json"              # roasters, contexts, Artisan setups
BEANCAVE_LISTS_JSON = Path(__file__).parent / "data/beancave_beans.json"  # countries, processes, species, varieties

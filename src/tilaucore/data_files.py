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

"""The data files of the shared library, found here by both apps."""

from pathlib import Path

# Each named from this file, so the desktop's doctrine test checks it is really there.
ROASTERS_JSON = Path(__file__).parent / "data/roasters.json"              # roasters, contexts, Artisan setups
BEANCAVE_LISTS_JSON = Path(__file__).parent / "data/beancave_beans.json"  # countries, processes, species, varieties

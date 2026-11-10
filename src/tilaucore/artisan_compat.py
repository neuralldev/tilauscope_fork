# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2025-2026 Tilau
# This file is part of TilauScope.

"""The units and stored values of a roast file (tilaucore.units), under the names the callers use.

The RoR is tilaucore.ror.
"""

from __future__ import annotations

from tilaucore.units import (WEIGHT_UNITS, c_from_f, convert_temp, convert_weight, decode_escaped, f_from_c,
                             ror_c_from_f, ror_f_from_c, slider_from_event)

weight_units = WEIGHT_UNITS
convertWeight = convert_weight  # noqa: N816
decodeLocalStrict = decode_escaped  # noqa: N816
events_internal_to_external_value = slider_from_event
fromFtoCstrict = c_from_f  # noqa: N816
fromCtoFstrict = f_from_c  # noqa: N816
RoRfromFtoCstrict = ror_c_from_f  # noqa: N816
RoRfromCtoFstrict = ror_f_from_c  # noqa: N816
convertTemp = convert_temp  # noqa: N816

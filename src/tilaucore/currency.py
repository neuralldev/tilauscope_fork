# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2025-2026 Tilau
# This file is part of TilauScope.

"""The currencies a green-coffee price is given in, shared by both apps."""

# ISO code → symbol of the currencies offered in Config › BeanCave.
CURRENCIES: dict[str, str] = {
    'EUR': '€', 'USD': '$', 'GBP': '£', 'CHF': 'CHF', 'CAD': 'CA$', 'AUD': 'A$',
    'NZD': 'NZ$', 'JPY': '¥', 'CNY': 'CN¥', 'KRW': '₩', 'TWD': 'NT$', 'HKD': 'HK$',
    'SGD': 'S$', 'INR': '₹', 'SEK': 'kr', 'NOK': 'kr', 'DKK': 'kr', 'PLN': 'zł',
    'CZK': 'Kč', 'BRL': 'R$', 'MXN': 'MX$', 'ZAR': 'R',
}

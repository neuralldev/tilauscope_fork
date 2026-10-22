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

"""The currencies a green-coffee price is given in, shared by both apps."""

# ISO code → symbol of the currencies offered in Config › BeanCave.
CURRENCIES: dict[str, str] = {
    'EUR': '€', 'USD': '$', 'GBP': '£', 'CHF': 'CHF', 'CAD': 'CA$', 'AUD': 'A$',
    'NZD': 'NZ$', 'JPY': '¥', 'CNY': 'CN¥', 'KRW': '₩', 'TWD': 'NT$', 'HKD': 'HK$',
    'SGD': 'S$', 'INR': '₹', 'SEK': 'kr', 'NOK': 'kr', 'DKK': 'kr', 'PLN': 'zł',
    'CZK': 'Kč', 'BRL': 'R$', 'MXN': 'MX$', 'ZAR': 'R',
}

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
# Tilau 2026

"""The certificate authorities HTTPS is checked against in the built app.

The OpenSSL the build carries looks for them in a Python.framework folder that no Mac has, so
Python's own HTTPS calls (the coffee library, urllib) refused every certificate. certifi's
bundle ships inside the app: OpenSSL reads it through SSL_CERT_FILE.
"""

from __future__ import annotations

import os
from collections.abc import MutableMapping


def use_bundled_certificates(environ: MutableMapping[str, str] = os.environ) -> None:
    """Point OpenSSL at certifi's authorities, unless a certificate file was already chosen."""
    if environ.get("SSL_CERT_FILE"):
        return
    try:
        import certifi  # noqa: PLC0415
    except ImportError:
        return
    path = certifi.where()
    if os.path.isfile(path):
        environ["SSL_CERT_FILE"] = path

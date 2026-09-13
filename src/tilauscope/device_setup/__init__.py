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

"""Devices — the part of Artisan's Config › Device a home roaster uses.

What reads the roaster, the extra devices behind the counters, and where room
conditions come from. Everything is edited as a draft (``draft.py``) and written
to Artisan in one go on Save; ``artisan_mirror.py`` replays the few pieces of
Artisan's own dialog that have to run for it.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from artisanlib.main import ApplicationWindow  # noqa: F401

_log: Final[logging.Logger] = logging.getLogger(__name__)

_open_dialog: Any = None   # the one Devices window, while it is open


def open_device_setup(aw: 'ApplicationWindow') -> None:
    """Open the Devices window, or bring the open one forward.

    Refused while monitoring: Artisan greys its own device menu for the same
    reason — the sampling thread reads the very lists this window rewrites.
    """
    global _open_dialog  # noqa: PLW0603
    from PyQt6 import sip
    from PyQt6.QtWidgets import QApplication, QMessageBox

    from tilauscope.tilauscope_types import show_styled_message

    main = getattr(aw, 'tilauscope_main', None)
    parent = main if main is not None and main.isVisible() else aw
    if aw.qmc.flagon:
        show_styled_message(
            parent,
            QApplication.translate('tilauscope_devices', 'Devices'),
            QApplication.translate(
                'tilauscope_devices',
                'Devices cannot be changed while the roaster is being read. '
                'Turn monitoring off first.'),
            QMessageBox.Icon.Warning)
        return
    if _open_dialog is not None and not sip.isdeleted(_open_dialog) and _open_dialog.isVisible():
        _open_dialog.raise_()
        _open_dialog.activateWindow()
        return
    from tilauscope.device_setup.dialog import DeviceSetupDialog
    _open_dialog = DeviceSetupDialog(parent, aw)
    _open_dialog.show()

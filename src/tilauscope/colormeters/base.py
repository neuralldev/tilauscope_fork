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


"""Facade every Bluetooth colour meter driver exposes to the screens."""

from PyQt6.QtCore import QObject, pyqtSignal


class ColorMeter(QObject): # pyright: ignore [reportGeneralTypeIssues] # Argument to class must be a base class
    """A colour meter that connects on creation and relays its readings.

    Signals are emitted on the GUI thread.
    """
    connected_signal = pyqtSignal()
    disconnected_signal = pyqtSignal()
    reading_signal = pyqtSignal(object)   # ColorReading

    def _drop_subscribers(self) -> None:
        """Disconnect every slot; PyQt raises TypeError when a signal has none."""
        for signal in (self.reading_signal, self.connected_signal, self.disconnected_signal):
            try:
                signal.disconnect()
            except TypeError:
                pass

    def stop(self) -> None:
        """Drop every subscriber and release the BLE link."""
        raise NotImplementedError

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

"""Left-to-right layout that wraps onto a new line when it runs out of width.

Qt ships no such layout. Used wherever a variable number of buttons or
counters has to fill whatever width the window happens to have.
"""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, QSize, Qt
from PyQt6.QtWidgets import QLayout


class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=0, spacing=-1):
        super().__init__(parent)
        # Initialize attributes BEFORE setting margins or adding items
        self._height_cache = {}
        self._cached_min_size = None
        self.items = []

        if parent is not None:
            self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)

    def invalidate(self):
        """Clear layout caches with safety checks."""
        # Use hasattr to prevent the AttributeError during early initialization
        if hasattr(self, '_height_cache'):
            self._height_cache.clear()
        if hasattr(self, '_cached_min_size'):
            self._cached_min_size = None
        super().invalidate()

    def __del__(self):
        while self.items:
            self.takeAt(0)

    def addItem(self, item):
        self.items.append(item)
        self.invalidate() # Clear caches when items are added

    def count(self):
        return len(self.items)

    def itemAt(self, index):
        return self.items[index] if 0 <= index < len(self.items) else None

    def takeAt(self, index):
        if 0 <= index < len(self.items):
            self.invalidate()
            return self.items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        # Optimization: Return cached height if we already calculated it for this width
        if width in self._height_cache:
            return self._height_cache[width]

        h = self._do_layout(QRect(0, 0, width, 0), True)
        self._height_cache[width] = h
        return h

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        if self._cached_min_size:
            return self._cached_min_size

        size = QSize()
        for item in self.items:
            size = size.expandedTo(item.minimumSize())

        margin = self.contentsMargins().left()
        size += QSize(2 * margin, 2 * margin)
        self._cached_min_size = size
        return size

    def _do_layout(self, rect, test_only):
        """Perform the actual layout logic."""
        m_left, m_top, m_right, m_bottom = self.getContentsMargins()
        x = rect.x() + m_left
        y = rect.y() + m_top
        line_height = 0
        spacing = self.spacing()
        right_limit = rect.right() - m_right

        for item in self.items:
            # OPTIMIZATION: Call sizeHint() exactly ONCE per item.
            s_hint = item.sizeHint()
            item_w = s_hint.width()
            item_h = s_hint.height()

            next_x = x + item_w + spacing

            # If we exceed the width, wrap to the next line
            if next_x - spacing > right_limit and line_height > 0:
                x = rect.x() + m_left
                y = y + line_height + spacing
                next_x = x + item_w + spacing
                line_height = 0

            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), s_hint))

            x = next_x
            line_height = max(line_height, item_h)

        return y + line_height + m_bottom - rect.y()

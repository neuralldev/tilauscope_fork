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

``addBreak`` marks a wrap the width cannot undo: the event-button bar has rows
the operator chose, and those must survive a panel wide enough to hold two of
them side by side.

``centered`` centres the block as a whole rather than each line: every line
keeps the same left edge, so adding an item to one line never slides the others
out from under the hand that was reaching for them.
"""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, QSize, Qt
from PyQt6.QtWidgets import QLayout


class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=0, spacing=-1, centered=False):
        super().__init__(parent)
        # Initialize attributes BEFORE setting margins or adding items
        self._height_cache = {}
        self._cached_min_size = None
        self._centered = centered
        self.items = []
        # Indices after which the line ends whatever the width allows. Recorded
        # by position, so a break belongs to the item that was last added when
        # it was declared; removing items afterwards would shift them.
        self._break_after = set()

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
        # Reached during garbage collection, where the C++ half may already be
        # gone: anything raising here surfaces as an unraisable exception with
        # no frame of ours in it.
        try:
            while self.items:
                self.takeAt(0)
        except (AttributeError, RuntimeError):
            pass

    def addItem(self, item):
        self.items.append(item)
        self.invalidate() # Clear caches when items are added

    def addBreak(self):
        """End the current line after the item added last."""
        if self.items:
            self._break_after.add(len(self.items) - 1)
            self.invalidate()

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

    def _build_lines(self, available, spacing):
        """Group the items into lines, without placing any of them yet.

        Returns ``[(items_with_hints, line_width, line_height)]``. An item that
        does not fit still opens a line of its own rather than vanishing.
        """
        lines = []
        current, width, height = [], 0, 0
        last = len(self.items) - 1
        for index, item in enumerate(self.items):
            # OPTIMIZATION: Call sizeHint() exactly ONCE per item.
            hint = item.sizeHint()
            needed = hint.width() if not current else width + spacing + hint.width()
            if current and needed > available:
                lines.append((current, width, height))
                current, width, height = [], 0, 0
                needed = hint.width()
            current.append((item, hint))
            width = needed
            height = max(height, hint.height())
            if index in self._break_after and index < last:
                lines.append((current, width, height))
                current, width, height = [], 0, 0
        if current:
            lines.append((current, width, height))
        return lines

    def _do_layout(self, rect, test_only):
        """Perform the actual layout logic."""
        m_left, m_top, m_right, m_bottom = self.getContentsMargins()
        spacing = self.spacing()
        left = rect.x() + m_left
        available = rect.right() - m_right - left
        lines = self._build_lines(available, spacing)
        if not lines:
            return m_top + m_bottom

        # The block is as wide as its widest line; a block wider than the box
        # gets no offset at all, which lands it back on the left margin.
        block_w = max(width for _items, width, _height in lines)
        offset = max(0, (available - block_w) // 2) if self._centered else 0

        y = rect.y() + m_top
        for items, _width, line_height in lines:
            x = left + offset
            for item, hint in items:
                if not test_only:
                    item.setGeometry(QRect(QPoint(x, y), hint))
                x += hint.width() + spacing
            y += line_height + spacing
        return y - spacing + m_bottom - rect.y()

#
# ABOUT
# annotation

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
# TiLau 2025

import logging
from typing import Final
from PyQt6.QtCore import Qt, QSettings, pyqtSlot # @UnusedImport @Reimport  @UnresolvedImport
from PyQt6.QtWidgets import QLabel, QToolButton, QApplication

from tilauscope.tilauscope_types import _IS_MACOS, _IS_WINDOWS

_log: Final[logging.Logger] = logging.getLogger(__name__)

class TilauAnnotation(QLabel):
    def __init__(self, parent=None, graph=None):
        super().__init__(parent)
        self.canvas_parent = parent # This should be the MplCanvas instance
        self.graph = graph
        # Optional CoachViewToggle mirrored on this annotation's show/hide.
        # Only the roast annotation sets this; the PID label leaves it None.
        self.companion: 'CoachViewToggle | None' = None

        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setStyleSheet("""
            QLabel {
                background-color: rgba(24, 24, 37, 0.7);
                color: #ffffff;
                border: 1px solid #555555;
                padding: 6px;
                border-radius: 4px;
                font-size: 11px;
            }
        """)
        self.setWordWrap(False)
        self.setTextFormat(Qt.TextFormat.RichText)
        self.hide()
    
    def update_visibility(self):
        if self.parentWidget() and not self.parentWidget().isVisible():
            self.hide()
            if _IS_WINDOWS:
                self.update()
            
    def show_at(self, x_data: float, y_data: float, html: str) -> None:
        """
        Positions the label based on graph coordinates with High-DPI support.

        Placement rules:
        - Normal (room on the right of the data point): label floats right,
          vertically centred on BT.
        - Overflow (no room on the right):
            * BT in the upper 80 % of the axes area -> anchor to BOTTOM corner
            * Otherwise                              -> anchor to TOP corner
          Horizontal position is clamped near the data point inside the axes area.

        Transient guard: if the data point projects outside the axes bounding box
        (happens for 1-2 cycles right after CHARGE while the x-axis range is being
        recalculated), the label is hidden for that cycle to avoid a phantom jump
        to the canvas corner.
        """
        if not self.canvas_parent or self.graph is None or self.graph.ax is None:
            _log.error("Canvas parent or its axes not found.")
            return

        self.setText(html)
        self.adjustSize()

        # 1. High-DPI ratio
        ratio = self.devicePixelRatioF()

        # 2. Axes bounding box (physical px, Matplotlib origin = bottom-left)
        ax_bbox = self.graph.ax.get_window_extent()
        if ax_bbox.width <= 0 or ax_bbox.height <= 0:
            # Axes not yet laid out — skip this cycle
            self.hide()
            return

        # 3. Data point -> physical display pixels
        display_pos = self.graph.ax.transData.transform((x_data, y_data))

        # 4. Logical pixels (Qt uses logical coords for move())
        logical_x = display_pos[0] / ratio
        logical_y = display_pos[1] / ratio

        # 5. Axes bbox in logical px, Qt coords (origin = top-left)
        canvas_w  = self.canvas_parent.width()
        canvas_h  = self.canvas_parent.height()
        ax_left   = ax_bbox.x0 / ratio
        ax_right  = ax_bbox.x1 / ratio
        ax_top    = canvas_h - ax_bbox.y1 / ratio
        ax_bottom = canvas_h - ax_bbox.y0 / ratio
        ax_height = max(ax_bottom - ax_top, 1)

        # 6. Transient guard
        # If the projected x is outside the axes area the canvas transform is
        # stale (x-axis range changed but not yet redrawn). Hide for this cycle.
        MARGIN = 20  # px tolerance to absorb rounding
        if logical_x < ax_left - MARGIN or logical_x > ax_right + MARGIN:
            self.hide()
            return

        # 7. Qt Y of the data point
        qt_y  = canvas_h - logical_y
        lbl_w = self.width()
        lbl_h = self.height()
        gap   = 12

        # 8. Placement decision
        if logical_x + gap + lbl_w <= canvas_w:
            # Normal: right of data point, vertically centred
            final_x = int(logical_x + gap)
            final_y = int(qt_y - lbl_h / 2)
            final_y = max(int(ax_top), min(final_y, int(ax_bottom - lbl_h)))

        else:
            # Overflow: top or bottom corner depending on BT position
            # bt_rel: 0.0 = axes bottom (cold), 1.0 = axes top (hot)
            bt_rel = (ax_bottom - qt_y) / ax_height
            if bt_rel >= 0.80:
                # BT in upper 20 % -> go to BOTTOM corner
                final_y = int(ax_bottom - lbl_h) - 4
            else:
                # Everything else -> go to TOP corner (away from DeltaET curve)
                final_y = int(ax_top) + 4

            # Horizontal: near data point, shifted left, clamped in axes area
            final_x = int(logical_x - gap - lbl_w)
            final_x = max(int(ax_left), min(final_x, int(ax_right - lbl_w)))

        # 9. Final safety clamp against canvas bounds
        final_x = max(0, min(final_x, canvas_w - lbl_w))
        final_y = max(0, min(final_y, canvas_h - lbl_h))

        self.move(final_x, final_y)
        self.show()
        if self.companion is not None:
            self.companion.sync_show()

    def hide(self) -> None:
        # Mirror visibility onto the companion toggle (if any). Covers every
        # external .hide() call site as well as update_visibility().
        super().hide()
        if getattr(self, 'companion', None) is not None:
            self.companion.hide()


class CoachViewToggle(QToolButton):
    """Small fixed corner button on the roast graph that flips the roast
    annotation between the simplified guided 'coach' view and the full expert
    data table. Visible only in Guided operator level. ## TILAU ##

    Lives parented to the Matplotlib canvas; mirrors the roast annotation's
    visibility via TilauAnnotation.companion. The chosen view is persisted in
    QSettings and cached on the graph as ``_annotation_expert_view`` for O(1)
    reads in the 1-4 Hz formatting path — this widget never reads QSettings nor
    calls the translator outside of state changes.
    """

    _MARGIN: Final[int] = 10
    _SIZE:   Final[int] = 28

    def __init__(self, canvas, graph):
        super().__init__(canvas)
        self.graph = graph
        self._allowed: bool = False
        self.setFixedSize(self._SIZE, self._SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setStyleSheet("""
            QToolButton {
                background-color: rgba(24, 24, 37, 0.7);
                border: 1px solid #45475A;
                border-radius: 6px;
                font-size: 14px;
            }
            QToolButton:hover { border: 1px solid #89B4FA; }
            QToolTip {
                background-color: #2D2F3F; color: white;
                border: 1px solid #585B70; padding: 5px;
                border-radius: 3px; font-size: 11px;
            }
        """)
        self.clicked.connect(self._on_click)
        self._refresh_glyph()
        self.hide()

    def set_allowed(self, allowed: bool) -> None:
        """Guided ↔ Expert gating. Not on the hot path."""
        self._allowed = allowed
        if not allowed:
            self.hide()
        self._refresh_glyph()

    def sync_show(self) -> None:
        """Reposition to the top-right corner and show. Called each draw cycle
        when the roast annotation shows — kept to a cheap move()/show(), no
        translator calls, no glyph rebuild."""
        if not self._allowed:
            self.hide()
            return
        # Top-left corner, just left of the graph title — easier to spot than the
        # top-right corner (which clashes with Artisan's own status glyph).
        self.move(self._MARGIN, self._MARGIN)
        self.show()
        self.raise_()

    def _on_click(self) -> None:
        g = self.graph
        g._annotation_expert_view = not getattr(g, '_annotation_expert_view', False)
        QSettings().setValue("tilauscope/annotation_expert_view", g._annotation_expert_view)
        self._refresh_glyph()
        try:
            g.DrawRoastAnnotation()  # immediate refresh, don't wait for next tick
        except Exception as e: # pylint: disable=broad-except
            _log.exception(e)

    def _refresh_glyph(self) -> None:
        """Glyph reflects the CURRENT view; tooltip says what a click switches to.
        Only called on state changes (init / allowed / click), never per cycle."""
        expert = getattr(self.graph, '_annotation_expert_view', False)
        self.setText("📊" if expert else "🎯")
        if expert:
            self.setToolTip(QApplication.translate(
                "tilauscope", "Expert data view — click for the simplified coach view"))
        else:
            self.setToolTip(QApplication.translate(
                "tilauscope", "Coach view — click for the full expert data view"))
#
# ABOUT
# annotation cards drawn over the roast curve

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

"""The two cards that float over the roast curve.

One reports the roast — phase, milestones reached, what is coming. The other
reports the preheat while the drum climbs to its target. Only one is ever on
screen: before the charge the preheat card, after it the roast card.

They were drawn on Artisan's canvas and placed through matplotlib transforms.
Here they are placed from the curve widget's own projection, which already
speaks in logical widget pixels — so the device-ratio arithmetic the matplotlib
placement needed disappears rather than being ported.

The placement rules themselves are unchanged, because they were never about
matplotlib: float to the right of the reading when there is room, otherwise
retreat to whichever corner the bean is furthest from, and stay inside the
tracing area either way.
"""

from __future__ import annotations

import logging
from typing import Any, Final

from PyQt6.QtCore import QPointF, QSettings, Qt
from PyQt6.QtWidgets import QApplication, QLabel, QToolButton

from artisanlib.util import convertTemp
from tilauscope.graph import annotation_text as text
from tilauscope.graph import forecast
from tilauscope.graph.common import marked, report_once
from tilauscope.theme_qss import tint, tooltip_qss
from tilauscope.tilauscope_types import THEME

_log: Final[logging.Logger] = logging.getLogger(__name__)

#: Distance between the reading and the card that comments on it.
_GAP: Final[int] = 12
#: Above this share of the tracing height, the card gives up the top corner.
_HIGH_BEAN: Final[float] = 0.80
#: Where the chosen view is remembered between sessions.
_VIEW_KEY: Final[str] = 'tilauscope/annotation_expert_view'
_TOGGLE_SIZE: Final[int] = 28


def _card_qss() -> str:
    return (f"QLabel {{ background-color: rgba(24, 24, 37, 0.7);"
            f" color: {THEME['TEXT']}; border: 1px solid {THEME['BORDER']};"
            f" padding: 6px; border-radius: 4px; font-size: 11px; }}")


class FloatingAnnotation(QLabel):
    """A card anchored to one reading on the curve."""

    def __init__(self, host: Any) -> None:
        super().__init__(host)
        self._host = host
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setWordWrap(False)
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setStyleSheet(_card_qss())
        self.hide()

    def show_at(self, point: QPointF, html: str,
                clear_of: float | None = None) -> None:
        """Place the card against a projected reading and show it.

        `clear_of` is an abscissa the card must not cover — the forecast line,
        which is the very thing the card counts down to. The bean walks towards
        it, so beside the reading is exactly where the card ends up sitting on
        it.
        """
        rect = self._host.plot_rect()
        if rect.width() <= 1 or rect.height() <= 1:
            self.hide()
            return

        self.setText(html)
        self.adjustSize()
        w, h = self.width(), self.height()
        x, y = point.x(), point.y()

        left: int | None = None
        top = 0
        if x + _GAP + w <= self._host.width():
            # Room on the right: float beside the reading, level with it.
            left = int(x + _GAP)
            top = int(y - h / 2)
            top = max(int(rect.top()), min(top, int(rect.bottom() - h)))
            if clear_of is not None and left <= clear_of <= left + w:
                # Slide past the line rather than over it, while the roast still
                # leaves room on its far side. Once it does not, the card is
                # better off behind the bean than on top of the target.
                beyond = int(clear_of + _GAP)
                left = beyond if beyond + w <= self._host.width() else None
        if left is None:
            # No room: retreat to a corner, choosing the one the bean is not in.
            share = (rect.bottom() - y) / max(rect.height(), 1.0)
            top = (int(rect.bottom() - h) - 4 if share >= _HIGH_BEAN
                   else int(rect.top()) + 4)
            left = int(x - _GAP - w)
            left = max(int(rect.left()), min(left, int(rect.right() - w)))

        left = max(0, min(left, self._host.width() - w))
        top = max(0, min(top, self._host.height() - h))
        self.move(left, top)
        self.show()
        self.raise_()

    def show_under(self, point: QPointF, html: str) -> None:
        """Place the card just below a horizontal reference and show it.

        For a card that comments on a line rather than on a reading: sitting
        beside the line would cover it, and the line is what is being waited
        for.
        """
        rect = self._host.plot_rect()
        if rect.width() <= 1 or rect.height() <= 1:
            self.hide()
            return
        self.setText(html)
        self.adjustSize()
        w, h = self.width(), self.height()
        left = int(min(max(point.x() + _GAP, rect.left()), rect.right() - w))
        top = int(min(max(point.y() + _GAP, rect.top()), rect.bottom() - h))
        self.move(max(0, min(left, self._host.width() - w)),
                  max(0, min(top, self._host.height() - h)))
        self.show()
        self.raise_()


class CoachViewToggle(QToolButton):
    """Flips the roast card between the guided coach view and the expert table.

    Shown only at the Guided operator level, where the coach view is the point:
    an operator who has asked for the full table has already said which view
    they want, and a button that switches away from it is one more thing to
    read mid-roast.

    The chosen view is persisted, and cached on the layer — this widget reads
    settings and calls the translator on state changes only, never per cycle.
    """

    def __init__(self, host: Any, layer: AnnotationLayer) -> None:
        super().__init__(host)
        self._layer = layer
        self.setFixedSize(_TOGGLE_SIZE, _TOGGLE_SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setStyleSheet(f"""
            QToolButton {{
                background-color: {tint('SURFACE', 0.7)};
                border: 1px solid {THEME['SURFACE1']};
                border-radius: 6px;
                font-size: 14px;
            }}
            QToolButton:hover {{ border: 1px solid {THEME['ACCENT']}; }}
            {tooltip_qss()}
        """)
        self.clicked.connect(self._on_click)
        self.refresh_glyph()
        self.hide()

    def _on_click(self) -> None:
        self._layer.expert_view = not self._layer.expert_view
        QSettings().setValue(_VIEW_KEY, self._layer.expert_view)
        self.refresh_glyph()
        # Immediate: waiting for the next tick makes the button feel broken on
        # a screen that only refreshes once a second.
        self._layer.tick()

    def refresh_glyph(self) -> None:
        """The glyph names the view you are in; the tooltip names the one a
        click would give. Called on state changes only."""
        expert = self._layer.expert_view
        self.setText('📊' if expert else '🎯')
        if expert:
            self.setToolTip(QApplication.translate(
                'tilauscope', 'Expert data view — click for the simplified coach view'))
        else:
            self.setToolTip(QApplication.translate(
                'tilauscope', 'Coach view — click for the full expert data'))


class AnnotationLayer:
    """Owns the two cards and decides, each tick, which one has something to say.

    It also owns which view the roast card is written in. That choice used to be
    read off the canvas by the formatter itself; here the layer holds it and
    passes it down, so the formatting stays a function of its arguments.
    """

    def __init__(self, host: Any, aw: Any) -> None:
        self._host = host
        self._aw = aw
        self.roast = FloatingAnnotation(host)
        self.preheat = FloatingAnnotation(host)
        # Cached once: the roast card is written on every tick and must never
        # go to settings to find out how.
        self.expert_view: bool = bool(
            QSettings().value(_VIEW_KEY, False, type=bool))
        # Guided only — see CoachViewToggle. Read once here so a layer built
        # before the screen has told it the level is already right; the screen
        # calls set_coach_allowed when the operator changes it.
        self._coach_allowed: bool = (
            QSettings().value('tilauscope/operator_level', 'guided', type=str) == 'guided')
        #: Charge-relative seconds at which the next milestone is due, held
        #: still enough to draw. None whenever no forecast is honest. The curve
        #: reads it when it paints; computing it twice would mean walking the
        #: phase state twice for one answer.
        self.forecast_t: float | None = None
        self.forecast_temp_c: float | None = None
        self._smoother = forecast.Smoother()
        self.view_toggle = CoachViewToggle(host, self)

    def set_coach_allowed(self, allowed: bool) -> None:
        """Guided ↔ the other levels. Follows the operator level, not the tick."""
        self._coach_allowed = allowed
        if not allowed:
            self.view_toggle.hide()
        else:
            self.view_toggle.refresh_glyph()

    # ── the tick ────────────────────────────────────────────────────────
    def tick(self) -> None:
        """Refresh both cards. Never raises: an annotation that fails is a
        missing card, not a lost screen."""
        try:
            qmc = getattr(self._aw, 'qmc', None)
            if qmc is None or not getattr(qmc, 'timex', None):
                self._hide_all()
                return
            if marked(getattr(qmc, 'timeindex', ()), 0):
                self.preheat.hide()
                if not getattr(qmc, 'flagstart', False):
                    # Nothing is being recorded any more: the operator has
                    # stopped, or this is a roast read back from a file. Either
                    # way a card saying what to do next about a roast where
                    # nothing is left to do is a leftover — after a stop it sat
                    # there announcing the cooling phase.
                    self._hide_all()
                    return
                # The operator's own switch, kept from where this lived on the
                # Artisan canvas: it has always governed the roast card and
                # never the preheat monitor, and moving the drawing is no
                # reason to change what a setting means.
                if not getattr(self._aw, 'TilauScopeAnnotation', False):
                    self.roast.hide()
                    self.view_toggle.hide()
                    self.forecast_t = self.forecast_temp_c = None
                    self._smoother.reset()
                    return
                # The forecast abscissa is only current once the card has been
                # built: building it is what republishes the forecast.
                html = self._roast_html(qmc)
                shown = self._place(self.roast, qmc, html, self._forecast_x())
                # The toggle follows the card it switches: left standing over a
                # card that is not there, it offers to change nothing.
                self._place_toggle(shown)
            elif self._preheat_due():
                self.roast.hide()
                self.view_toggle.hide()
                self._place_preheat(qmc)
            else:
                self._hide_all()
        except Exception:
            _log.exception('AnnotationLayer: tick failed')
            self._hide_all()

    def _hide_all(self) -> None:
        self.roast.hide()
        self.preheat.hide()
        self.view_toggle.hide()
        self.forecast_t = self.forecast_temp_c = None
        self._smoother.reset()

    def _place_toggle(self, shown: bool) -> None:
        """Above the plot on the left, opposite the view selector.

        Never over the tracing area: the button would sit on the curve it is
        there to explain, and the milestone chips run along that same top edge.
        """
        if not (shown and self._coach_allowed):
            self.view_toggle.hide()
            return
        rect = self._host.plot_rect()
        if rect.width() <= 1:
            self.view_toggle.hide()
            return
        self.view_toggle.move(int(rect.left()),
                              max(0, int(rect.top()) - _TOGGLE_SIZE - 5))
        self.view_toggle.show()
        self.view_toggle.raise_()

    # ── placement ───────────────────────────────────────────────────────
    def _place(self, card: FloatingAnnotation, qmc: Any, html: str | None,
               clear_of: float | None = None) -> bool:
        if not html:
            card.hide()
            return False
        point = self._anchor(qmc)
        if point is None:
            # The reading is outside the drawn window — which happens for a
            # cycle or two whenever the window moves. A card left where it was
            # would point at the wrong moment.
            card.hide()
            return False
        card.show_at(point, html, clear_of)
        return True

    def _place_preheat(self, qmc: Any) -> None:
        """Against the target line, not against the head of the climb.

        Falls back to the reading when the target is off the axis — a card in
        the wrong place still beats no card during a preheat.
        """
        # Once the drum is there the chart says CHARGE NOW on the head of the
        # climb, in the one place the operator is already looking. A card
        # repeating it beside the target is a second instruction for a single
        # decision, and the countdown it carried has nothing left to count.
        preheat = getattr(self._host, '_preheat', None)
        if preheat is not None and getattr(preheat, 'ready', False):
            self.preheat.hide()
            return
        html = self._preheat_html(qmc)
        if not html:
            self.preheat.hide()
            return
        point = self._host.preheat_target_point()
        if point is not None:
            self.preheat.show_under(point, html)
            return
        self._place(self.preheat, qmc, html)

    def _forecast_x(self) -> float | None:
        """Where the forecast line stands, or None when it is not drawn."""
        reader = getattr(self._host, 'forecast_x', None)
        return reader() if reader is not None else None

    def _anchor(self, qmc: Any) -> QPointF | None:
        """The latest bean reading, in widget coordinates."""
        timex = getattr(qmc, 'timex', None)
        temp2 = getattr(qmc, 'temp2', None)
        if not timex or not temp2:
            return None
        raw = temp2[-1]
        if raw is None or raw == -1:
            return None
        bean_c = convertTemp(float(raw), getattr(qmc, 'mode', 'C'), 'C')
        t = float(timex[-1])
        offset = self._host.charge_offset()
        if offset is not None:
            t -= offset
        return self._host.project(t, bean_c)

    # ── text ────────────────────────────────────────────────────────────
    def _preheat_due(self) -> bool:
        """Artisan's own PID running, or the TilauScope preheat driving the
        roaster. O(1), and asked on every tick."""
        pid = getattr(self._aw, 'pidcontrol', None)
        if pid is not None and getattr(pid, 'pidActive', False):
            return True
        preheat = getattr(self._aw, 'tilauPreheatingPid', None)
        return preheat is not None and getattr(preheat, 'active', False)

    def _roast_html(self, qmc: Any) -> str | None:
        _target, info = text.phase_and_target(qmc)
        raw = forecast.milestone(qmc, info)
        self._publish_forecast(qmc, info, raw)
        # The card gets the raw forecast: a countdown is expected to move, and
        # smoothing one only makes it lag. The chart gets the smoothed value.
        coach = self._coach_allowed and not self.expert_view
        return text.roast_card(qmc, raw if raw is not None else float(qmc.timex[-1]),
                               info, coach)

    def _publish_forecast(self, qmc: Any, info: dict, raw: float | None) -> None:
        shown = self._smoother.feed(raw)
        if shown is None:
            self.forecast_t = self.forecast_temp_c = None
            return
        offset = self._host.charge_offset()
        self.forecast_t = shown - offset if offset is not None else shown
        try:
            self.forecast_temp_c = convertTemp(
                float(info['target']), getattr(qmc, 'mode', 'C'), 'C')
        except (KeyError, TypeError, ValueError):
            self.forecast_t = self.forecast_temp_c = None

    def _preheat_html(self, qmc: Any) -> str | None:
        tx = float(qmc.timex[-1])
        temp1 = getattr(qmc, 'temp1', None) or [0.0]
        temp2 = getattr(qmc, 'temp2', None) or [0.0]
        et, bt = float(temp1[-1] or 0.0), float(temp2[-1] or 0.0)
        preheat = getattr(self._aw, 'tilauPreheatingPid', None)
        if preheat is not None and getattr(preheat, 'active', False):
            return text.preheat_card(qmc, preheat, et, bt)
        pid = getattr(self._aw, 'pidcontrol', None)
        if pid is None:
            report_once('AnnotationLayer: a preheat with no controller')
            return None
        return text.pid_card(qmc, pid, tx, et, bt)

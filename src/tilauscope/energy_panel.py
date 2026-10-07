#
# ABOUT
# Energy view: floating energy sheet, shared formatting.

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

"""What the operator sees of the energy session.

The sheet computes the bill of a saved roast once, when it opens — never
inside Artisan's update slot.
"""

import logging
from typing import Any, Final

from PyQt6.QtCore import QPoint, QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import (QApplication, QDialog, QFrame, QGridLayout,
                             QHBoxLayout, QLabel, QPushButton, QSizePolicy, QToolTip,
                             QVBoxLayout, QWidget)

from tilauscope.energy_model import (
    ESTIMATED, EXTRACTOR, HEATER_FROM_ARTISAN, HEATER_FROM_CONFIG, MEASURED, MIXED, NONE, ROASTER,
    EnergySession, Summary,
    Totals, phase_bounds, session_for_profile,
)
from tilauscope.energy_tap import EnergyTap
from tilauscope.theme_qss import base_qss
from tilauscope.tilauscope_types import THEME

_log: Final[logging.Logger] = logging.getLogger(__name__)

_WIDTH: Final[int] = 460
# Channel hues: heat for the roaster, air for the extractor. Categorical, so
# literal on purpose (see the theme rules on channel palettes).
_HUE: Final[dict[str, str]] = {ROASTER: "#FAB387", EXTRACTOR: "#89DCEB"}


# ── application wiring ───────────────────────────────────────────────────

def ensure_energy_tap(aw: Any) -> EnergyTap | None:
    """The one energy service of the application, created on first use and
    kept on `aw` so it outlives the TilauScope window."""
    tap = getattr(aw, "tilau_energy_tap", None)
    if tap is None:
        try:
            tap = EnergyTap(aw)
            aw.tilau_energy_tap = tap
        except Exception as e:  # pylint: disable=broad-except
            _log.warning("energy tap not started: %s", e)
            return None
    return tap


def green_kg(weight: Any) -> float:
    """Green mass in kg from Artisan's weight triple (in, out, unit), 0 when unknown."""
    try:
        from artisanlib.util import convertWeight, weight_units
        w = weight
        v = float(w[0] or 0)
        return convertWeight(v, weight_units.index(str(w[2])), weight_units.index("Kg")) if v > 0 else 0.0
    except Exception:  # pylint: disable=broad-except
        return 0.0


def summarize_profile(profile: dict, session: EnergySession) -> Summary:
    """The bill of a saved roast, on that profile's own milestones and weight."""
    return session.summarize(phase_bounds(profile.get("timex") or [], profile.get("timeindex") or []),
                             green_kg(profile.get("weight") or (0, 0, "g")))


# ── formatting ───────────────────────────────────────────────────────────

def fmt_power(w: float | None) -> str:
    if w is None:
        return "—"
    return f"{w:.0f} W" if w < 1000 else f"{w / 1000:.2f} kW"


def fmt_kwh(wh: float | None) -> str:
    return "—" if wh is None else f"{wh / 1000:.3f} kWh"


def provenance(tot: Totals | None) -> tuple[str, str, str]:
    """(glyph, colour, words) for a total. Colour never carries it alone."""
    kind = tot.provenance if tot is not None else NONE
    if kind == NONE:
        return "○", THEME['OVERLAY0'], QApplication.translate("tilauscope_energy", "Not tracked")
    word = {MEASURED: QApplication.translate("tilauscope_energy", "Measured"),
            ESTIMATED: QApplication.translate("tilauscope_common", "Estimated"),
            MIXED: QApplication.translate("tilauscope_energy", "Mixed")}[kind]
    colour = THEME['SUCCESS'] if kind == MEASURED else THEME['WARNING']
    if tot is not None and tot.incomplete:
        return "◐", colour, QApplication.translate("tilauscope_energy", "{0} · incomplete").format(word)
    return "●", colour, word


def _mono(size: int, weight: int = 400, color: str = "") -> str:
    col = f" color: {color};" if color else ""
    return (f"font-family: 'JetBrains Mono', monospace; font-size: {size}px;"
            f" font-weight: {weight};{col} background: transparent; border: none;")


def _channel_label(name: str) -> str:
    return (QApplication.translate("tilauscope_energy", "🔥 Roaster") if name == ROASTER
            else QApplication.translate("tilauscope_energy", "💨 Extractor"))


# ── power trace ──────────────────────────────────────────────────────────

class _PowerTrace(QWidget):
    """Power of each source over the session, in W, on the roast's own clock
    (time from CHARGE). Dotted where estimated; a grey band where no source
    was read. Hover names the instant and the power."""

    _MAX_POINTS: Final[int] = 400
    _LEFT, _RIGHT, _TOP, _BOTTOM = 46.0, 6.0, 14.0, 16.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session: EnergySession | None = None
        self._charge: float | None = None      # session axis
        self._drop: float | None = None
        self._scale = 0.0
        self.setFixedHeight(128)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_data(self, session: EnergySession | None, summary: Summary | None) -> None:
        self._session = session
        roast = summary.roast if summary is not None else None
        self._charge = roast.start if roast is not None else (
            summary.before_charge.end if summary is not None and summary.before_charge is not None
            and summary.after_drop is not None else None)
        self._drop = roast.end if roast is not None and not roast.open else None
        self.update()

    # ── geometry ─────────────────────────────────────────────────────────

    def _span(self) -> tuple[float, float]:
        s = self._session
        assert s is not None
        return s.start, max(s.end, s.start + 1.0)

    def _x(self, t: float) -> float:
        t0, t1 = self._span()
        return self._LEFT + (t - t0) / (t1 - t0) * (self.width() - self._LEFT - self._RIGHT)

    def _t(self, x: float) -> float:
        t0, t1 = self._span()
        return t0 + (x - self._LEFT) / max(1.0, self.width() - self._LEFT - self._RIGHT) * (t1 - t0)

    def _y(self, w: float) -> float:
        h = self.height() - self._TOP - self._BOTTOM
        return self._TOP + h - (w / self._scale) * h if self._scale > 0 else self._TOP + h

    def _clock(self, t: float) -> str:
        """m:ss from CHARGE (negative before it), else from the session start."""
        ref = self._charge if self._charge is not None else self._span()[0]
        d = t - ref
        sign = "−" if d < 0 else ""
        d = abs(int(round(d)))
        return f"{sign}{d // 60}:{d % 60:02d}"

    # ── painting ─────────────────────────────────────────────────────────

    def paintEvent(self, _event: Any) -> None:  # noqa: N802  (Qt override)
        # an exception escaping a Qt virtual takes the application down
        try:
            self._paint()
        except Exception as e:  # pylint: disable=broad-except
            _log.debug("power trace: %s", e)

    def _paint(self) -> None:
        s = self._session
        if s is None or s.end <= s.start or not s.channels:
            return
        peak = max([w for ch in s.channels.values() for w in ch.mw + ch.ew if w >= 0] or [0.0])
        if peak <= 0:
            return
        step = 250.0 if peak <= 1500 else 500.0
        self._scale = step * max(1, -(-peak // step))
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t0, t1 = self._span()
        bottom = self._y(0)
        mono = QFont("JetBrains Mono")
        mono.setPixelSize(9)
        p.setFont(mono)
        faint, grid = QColor(THEME['OVERLAY0']), QColor(THEME['BORDER'])

        # no-reading bands: time not covered by any measurement nor estimate
        band = QColor(THEME['SURFACE1'])
        band.setAlpha(90)
        for ch in s.channels.values():
            if not ch.mt:
                continue
            gaps = [(t0, ch.mt[0])] + [(a, b) for a, b in zip(ch.mt, ch.mt[1:], strict=False)
                                        if b - a > ch.max_gap_s] + [(ch.mt[-1], t1)]
            for a, b in gaps:
                if b - a > 1 and ch.integrate(a, b).unknown_s > 1:
                    rect = QRectF(self._x(a), self._TOP, self._x(b) - self._x(a), bottom - self._TOP)
                    p.fillRect(rect, band)
                    if rect.width() > 60:
                        p.setPen(faint)
                        p.drawText(rect, Qt.AlignmentFlag.AlignCenter,
                                   QApplication.translate("tilauscope_energy", "no reading"))

        # W grid and labels
        pen = QPen(grid)
        pen.setWidthF(1.0)
        v = 0.0
        while v <= self._scale + 1e-6:
            y = self._y(v)
            p.setPen(pen)
            p.drawLine(QPointF(self._LEFT, y), QPointF(self.width() - self._RIGHT, y))
            p.setPen(faint)
            p.drawText(QRectF(0, y - 6, self._LEFT - 6, 12),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       f"{v:.0f} W" if v < 1000 else f"{v / 1000:g} kW")
            v += step * (2 if self._scale / step > 4 else 1)

        # milestones: CHARGE / DROP, with the roast clock under them
        marks = [(t, name) for t, name in ((self._charge, "CHARGE"), (self._drop, "DROP")) if t is not None]
        mpen = QPen(QColor(THEME['ACCENT']))
        mpen.setStyle(Qt.PenStyle.DashLine)
        for t, name in marks:
            x = self._x(t)
            p.setPen(mpen)
            p.drawLine(QPointF(x, self._TOP), QPointF(x, bottom))
            p.setPen(QColor(THEME['ACCENT']))
            p.drawText(QRectF(x - 40, 0, 80, self._TOP), Qt.AlignmentFlag.AlignCenter, name)
        p.setPen(faint)
        labels = [(t0, self._clock(t0))] + [(t, self._clock(t)) for t, _ in marks] + [(t1, self._clock(t1))]
        for k, (t, text) in enumerate(labels):
            x = self._x(t)
            align = (Qt.AlignmentFlag.AlignLeft if k == 0 else
                     Qt.AlignmentFlag.AlignRight if k == len(labels) - 1 else Qt.AlignmentFlag.AlignHCenter)
            rx = x if k == 0 else x - 60 if k == len(labels) - 1 else x - 30
            p.drawText(QRectF(rx, bottom + 2, 60, self._BOTTOM - 2), align | Qt.AlignmentFlag.AlignTop, text)

        # the series
        for name, ch in s.channels.items():
            colour = QColor(_HUE.get(name, THEME['TEXT']))
            if ch.et:
                pen = QPen(colour)
                pen.setStyle(Qt.PenStyle.DotLine)
                pen.setWidthF(1.2)
                p.setPen(pen)
                steps = QPolygonF()
                times = ch.et + [s.end]
                for i, v in enumerate(ch.ew):
                    if v < 0:                        # estimate stopped: break the line
                        p.drawPolyline(steps)
                        steps = QPolygonF()
                        continue
                    steps.append(QPointF(self._x(times[i]), self._y(v)))
                    steps.append(QPointF(self._x(max(times[i], min(times[i + 1], s.end))), self._y(v)))
                p.drawPolyline(steps)
            if len(ch.mt) >= 2:
                pen = QPen(colour)
                pen.setWidthF(1.5)
                p.setPen(pen)
                stride = max(1, len(ch.mt) // self._MAX_POINTS)
                run = QPolygonF()
                prev: float | None = None
                for i in range(0, len(ch.mt), stride):
                    t = ch.mt[i]
                    if prev is not None and t - prev > ch.max_gap_s * stride:
                        p.drawPolyline(run)          # a gap breaks the line
                        run = QPolygonF()
                    run.append(QPointF(self._x(t), self._y(ch.mw[i])))
                    prev = t
                p.drawPolyline(run)

        # legend, in each source's hue
        x = self._LEFT + 4
        for name in s.channels:
            text = (QApplication.translate("Label", "Roaster") if name == ROASTER
                    else QApplication.translate("tilauscope_energy", "Extractor"))
            p.setPen(QColor(_HUE.get(name, THEME['TEXT'])))
            p.drawText(QRectF(x, self._TOP + 1, 120, 12), Qt.AlignmentFlag.AlignLeft, "— " + text)
            x += p.fontMetrics().horizontalAdvance("— " + text) + 12
        p.end()

    def mouseMoveEvent(self, event: Any) -> None:  # noqa: N802  (Qt override)
        try:
            s = self._session
            if s is None or not s.channels or event.position().x() < self._LEFT:
                QToolTip.hideText()
                return
            t = self._t(event.position().x())
            parts = []
            for name, ch in s.channels.items():
                w = _power_at(ch, t)
                label = (QApplication.translate("Label", "Roaster") if name == ROASTER
                         else QApplication.translate("tilauscope_energy", "Extractor"))
                parts.append(f"{label} {fmt_power(w)}")
            where = (QApplication.translate("tilauscope_energy", "{0} from CHARGE")
                     if self._charge is not None else
                     QApplication.translate("tilauscope_energy", "{0} from the start")).format(self._clock(t))
            QToolTip.showText(event.globalPosition().toPoint(), where + "\n" + "\n".join(parts), self)
        except Exception as e:  # pylint: disable=broad-except
            _log.debug("power trace hover: %s", e)


def _power_at(ch: Any, t: float) -> float | None:
    """Power the bill uses at `t`: the measured segment, else the estimate."""
    from bisect import bisect_right
    k = bisect_right(ch.mt, t) - 1
    if 0 <= k < len(ch.mt) - 1 and ch.mt[k + 1] - ch.mt[k] <= ch.max_gap_s:
        ta, tb = ch.mt[k], ch.mt[k + 1]
        return ch.mw[k] + (ch.mw[k + 1] - ch.mw[k]) * (t - ta) / (tb - ta)
    j = bisect_right(ch.et, t) - 1
    return ch.ew[j] if j >= 0 and ch.ew[j] >= 0 else None


# ── energy sheet ─────────────────────────────────────────────────────────

class EnergyPanel(QDialog):
    """Non-modal sheet of one saved roast (BeanCave)."""

    def __init__(self, aw: Any, parent: QWidget | None, profile: dict) -> None:
        super().__init__(parent)
        self.aw = aw
        self._profile = profile
        self._profile_session = session_for_profile(profile)
        self._drag_pos: QPoint | None = None
        self.setModal(False)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setFixedWidth(_WIDTH)
        self.setStyleSheet(base_qss() + f"""
            QDialog {{ background: {THEME['BG']}; border: 2px solid {THEME['ACCENT']};
                       border-radius: 10px; }}
            QLabel {{ color: {THEME['TEXT']}; background: transparent; border: none; }}
        """)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 14)
        root.setSpacing(8)

        head = QHBoxLayout()
        cap = QLabel(QApplication.translate("tilauscope_energy", "ENERGY"))
        cap.setStyleSheet(_mono(10, 700, THEME['SUBTEXT']) + " letter-spacing: 1px;")
        self._state = QLabel()
        self._state.setStyleSheet(_mono(10, 400, THEME['OVERLAY0']))
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(26, 26)
        close_btn.setProperty('variant', 'icon')
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.close)
        head.addWidget(cap)
        head.addStretch(1)
        head.addWidget(self._state)
        head.addWidget(close_btn)
        root.addLayout(head)

        hero = QHBoxLayout()
        self._total = QLabel()
        self._total.setStyleSheet(_mono(13, 700, THEME['TEXT']))
        self._total.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        hero.addStretch(1)
        hero.addWidget(self._total)
        root.addLayout(hero)

        self._trace = _PowerTrace()
        root.addWidget(self._trace)

        # Three fixed segments: only their contents change, never their size.
        phases = QHBoxLayout()
        phases.setSpacing(4)
        self._phase: dict[str, QLabel] = {}
        self._phase_box: dict[str, QFrame] = {}
        for key, title, tip, stretch in (
                ("before", QApplication.translate("Label", "Preheat"),
                 QApplication.translate("tilauscope_energy", "From monitoring ON to CHARGE, including any wait before preheating."), 1),
                ("roast", QApplication.translate("tilauscope_energy", "Roast"),
                 QApplication.translate("tilauscope_energy", "From CHARGE to DROP."), 2),
                ("after", QApplication.translate("Label", "Cooling"),
                 QApplication.translate("tilauscope_energy", "From DROP to monitoring OFF, including any wait after cooling."), 1)):
            box = QFrame()
            box.setObjectName("phase")
            box.setToolTip(tip)
            lay = QVBoxLayout(box)
            lay.setContentsMargins(8, 4, 8, 5)
            lay.setSpacing(0)
            t = QLabel(title.upper())
            t.setStyleSheet(_mono(9, 700, THEME['OVERLAY0']))
            v = QLabel("—")
            v.setStyleSheet(_mono(12, 700, THEME['TEXT']))
            lay.addWidget(t)
            lay.addWidget(v)
            self._phase[key] = v
            self._phase_box[key] = box
            phases.addWidget(box, stretch)
        root.addLayout(phases)

        self._rows = QGridLayout()
        self._rows.setHorizontalSpacing(12)
        self._rows.setVerticalSpacing(2)
        self._cells: dict[str, list[QLabel]] = {}
        r = 0
        for name in (ROASTER, EXTRACTOR):
            cells = [QLabel(_channel_label(name)), QLabel(), QLabel()]
            cells[1].setStyleSheet(_mono(11, 400, THEME['TEXT']))
            cells[1].setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            for c, cell in enumerate(cells):
                self._rows.addWidget(cell, r, c)
            note = QLabel()
            note.setWordWrap(True)
            note.setStyleSheet(f"color: {THEME['SUBTEXT']}; font-size: 11px;")
            self._rows.addWidget(note, r + 1, 0, 1, 3)
            cells.append(note)
            self._cells[name] = cells
            r += 2
        self._rows.setColumnStretch(0, 1)
        root.addLayout(self._rows)

        self._per_kg = QLabel()
        self._coverage = QLabel()
        self._coverage.setWordWrap(True)
        self._coverage.setStyleSheet(f"color: {THEME['SUBTEXT']}; font-size: 11px;")
        root.addWidget(self._per_kg)
        root.addWidget(self._coverage)

        self.refresh()

    # ── data ─────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        try:
            self._refresh()
        except Exception as e:  # pylint: disable=broad-except
            _log.debug("energy panel: %s", e)

    def _refresh(self) -> None:
        session = self._profile_session
        self._state.setText(
            QApplication.translate("tilauscope_energy", "Rebuilt from the saved curve")
            if session is not None and session.rebuilt
            else QApplication.translate("tilauscope_energy", "Saved roast") if session is not None
            else QApplication.translate("tilauscope_energy", "No energy data"))

        if session is None:
            self._total.setText("")
            for key in ("before", "roast", "after"):
                self._phase[key].setText("—")
            for name, cells in self._cells.items():
                self._fill_row(name, cells, None, None, None)
            self._per_kg.setText("")
            self._coverage.setText(QApplication.translate(
                "tilauscope_energy", "This roast carries no energy record."))
            self._trace.set_data(None, None)
            return

        summary = summarize_profile(self._profile, session)
        self._trace.set_data(session, summary)
        total = summary.total(summary.since_start)
        complete = summary.complete(summary.since_start)
        self._total.setText(
            (QApplication.translate("tilauscope_energy", "Total {0}") if complete
             else QApplication.translate("tilauscope_energy", "Known consumption {0}")).format(fmt_kwh(total.wh)))

        for key, period in (("before", summary.before_charge), ("roast", summary.roast),
                            ("after", summary.after_drop)):
            tot = summary.total(period.per_channel) if period is not None else None
            self._phase[key].setText(fmt_kwh(tot.wh) if tot is not None and tot.span_s > 0 else "—")
            box = self._phase_box[key]
            active = period is not None and period.open
            box.setStyleSheet(
                f"QFrame#phase {{ background: {THEME['SURFACE']}; border-radius: 6px;"
                f" border: 1px solid {THEME['ACCENT'] if active else THEME['BORDER']}; }}")
        if summary.roast_split:
            names = {"drying": QApplication.translate("Label", "Drying"),
                     "maillard": QApplication.translate("Label", "Maillard"),
                     "development": QApplication.translate("Label", "Development")}
            self._phase["roast"].setToolTip("\n".join(
                f"{names[n]}  {fmt_kwh(summary.total(p.per_channel).wh)}" for n, p in summary.roast_split))
        else:
            self._phase["roast"].setToolTip("")

        for name, cells in self._cells.items():
            self._fill_row(name, cells, session, summary, summary.since_start.get(name))

        if summary.wh_per_kg is not None:
            self._per_kg.setText(QApplication.translate(
                "tilauscope_energy", "Roast energy per kg green   {0} kWh/kg").format(f"{summary.wh_per_kg / 1000:.3f}"))
        elif summary.roast is None or summary.roast.open:
            self._per_kg.setText(QApplication.translate(
                "tilauscope_energy", "Roast energy per kg green   — (after DROP)"))
        elif green_kg(self._profile.get("weight")) <= 0:
            self._per_kg.setText(QApplication.translate(
                "tilauscope_energy", "Roast energy per kg green   — (green weight missing)"))
        else:
            self._per_kg.setText(QApplication.translate(
                "tilauscope_energy", "Roast energy per kg green   — (roast not fully covered)"))

        missing = [n for n in summary.expected
                   if summary.since_start.get(n) is None or summary.since_start[n].provenance == NONE]
        if complete:
            self._coverage.setText(QApplication.translate("tilauscope_energy", "Coverage: full period, every source tracked."))
        elif missing:
            self._coverage.setText(QApplication.translate(
                "tilauscope_energy", "Coverage: {0} not tracked — the figures leave it out.").format(
                    ", ".join(_channel_label(n) for n in missing)))
        else:
            share = min(summary.since_start[n].coverage for n in summary.expected)
            self._coverage.setText(QApplication.translate(
                "tilauscope_energy", "Coverage: {0} % of the period — the rest is left out.").format(f"{share * 100:.0f}"))

    def _fill_row(self, name: str, cells: list[QLabel], session: EnergySession | None,
                  summary: Summary | None, tot: Totals | None) -> None:
        included = summary is not None and name == EXTRACTOR and summary.extractor_included
        expected = summary is not None and (name in summary.expected or included)
        visible = name == ROASTER or expected or (session is not None and name in session.channels)
        for c in cells:
            c.setVisible(visible)
        if not visible:
            return
        cells[1].setText(fmt_kwh(tot.wh) if tot is not None and tot.provenance != NONE else "—")
        glyph, colour, words = provenance(tot)
        if included:
            words = QApplication.translate("tilauscope_energy", "Included in roaster meter")
        cells[2].setText(f"{glyph} {words}")
        cells[2].setStyleSheet(f"color: {colour}; font-size: 11px;")
        note = ""
        if tot is None or tot.provenance == NONE:
            if name == ROASTER and not included:
                note = QApplication.translate(
                    "tilauscope_energy", 'No power model for this roaster. Add an MQTT power sensor named '
                          '"roaster" to measure it.')
        elif tot.incomplete:
            note = QApplication.translate(
                "tilauscope_energy", "Meter silent for {0} s in all — that time is left out.").format(f"{tot.unknown_s:.0f}")
        elif tot.provenance in (ESTIMATED, MIXED) and session is not None and session.heater_from == HEATER_FROM_ARTISAN:
            note = QApplication.translate(
                "tilauscope_energy", "Estimated from the heater Artisan rates for this roaster ({0}) and the burner "
                                     "setting.").format(
                    f"{session.heater_w / 1000:.3g} kW")
        elif tot.provenance in (ESTIMATED, MIXED) and session is not None and session.heater_from == HEATER_FROM_CONFIG:
            note = QApplication.translate(
                "tilauscope_energy", "Estimated from the heater power set in TilauScope Config ({0}) and the burner "
                                     "setting.").format(f"{session.heater_w / 1000:.3g} kW")
        elif tot.provenance in (ESTIMATED, MIXED):
            note = QApplication.translate(
                "tilauscope_energy", "Estimated from the rated power and the burner setting.")
        cells[3].setText(note)
        cells[3].setVisible(bool(note))

    # ── frameless drag ───────────────────────────────────────────────────

    # Qt virtuals: an exception escaping them closes the application.
    def mousePressEvent(self, event: Any) -> None:  # noqa: N802
        try:
            if event.button() == Qt.MouseButton.LeftButton:
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        except Exception as e:  # pylint: disable=broad-except
            _log.debug("energy panel press: %s", e)

    def mouseMoveEvent(self, event: Any) -> None:  # noqa: N802
        try:
            if self._drag_pos is not None:
                self.move(event.globalPosition().toPoint() - self._drag_pos)
        except Exception as e:  # pylint: disable=broad-except
            _log.debug("energy panel move: %s", e)

    def mouseReleaseEvent(self, _event: Any) -> None:  # noqa: N802
        self._drag_pos = None

    def sizeHint(self) -> QSize:
        return QSize(_WIDTH, super().sizeHint().height())

#
# ABOUT
# Energy view: header pill, floating energy sheet, shared formatting.

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

The pill reads the tap's running totals only (O(1) per tick). The sheet
recomputes the phase bill on its own 1 s timer while open — never inside
Artisan's update slot.
"""

import logging
import time
from typing import Any, Final

from PyQt6.QtCore import QPoint, QPointF, QRectF, QSettings, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import (QApplication, QCheckBox, QDialog, QFrame, QGridLayout,
                             QHBoxLayout, QLabel, QPushButton, QSizePolicy, QToolTip,
                             QVBoxLayout, QWidget)

from tilauscope.energy_model import (
    ESTIMATED, EXTRACTOR, MEASURED, MIXED, NONE, ROASTER, EnergySession, Summary,
    Totals, phase_bounds, session_for_profile,
)
from tilauscope.energy_tap import (
    DUPLICATE, MISSING, OK, SETTING_EXTRACTOR_ON_ROASTER_METER, UNIT, EnergyTap,
)
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


def summarize_current(aw: Any, session: EnergySession, live: bool) -> Summary:
    qmc = aw.qmc
    return session.summarize(phase_bounds(qmc.timex, qmc.timeindex), green_kg(qmc.weight), live)


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
            ESTIMATED: QApplication.translate("tilauscope_energy", "Estimated"),
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


# ── header pill ──────────────────────────────────────────────────────────

class EnergyPill(QPushButton):
    """⚡ power now · energy since ON. Fixed width: a live figure never
    moves its neighbours."""

    def __init__(self, tap: EnergyTap, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tap = tap
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty('variant', 'icon')
        self.setFixedHeight(26)
        mono = QFont("JetBrains Mono")
        mono.setPixelSize(11)
        self.setFixedWidth(QFontMetrics(mono).horizontalAdvance("⚡ 88.88 kW · 88.888 kWh ●") + 24)
        self._colour = ""
        self.hide()
        tap.updated.connect(self.refresh)

    def refresh(self) -> None:
        try:
            tap = self._tap
            sess = tap.session
            # shown as soon as a reserved sensor exists, even before its first
            # reading: its sheet is where an unconfirmed unit gets fixed
            if not tap.live or sess is None or not (
                    sess.channels or any(v != MISSING for v in tap.status.values())):
                self.setVisible(False)
                return
            now = time.time()
            watts: float | None = None
            total = Totals()
            for name in sess.expected():
                ch = sess.channels.get(name)
                if ch is not None:
                    w, _ = ch.power_now(now)
                    if w is not None:
                        watts = (watts or 0.0) + w
                if name in tap.acc:
                    total += tap.acc[name]
            glyph, colour, words = provenance(total if total.span_s > 0 else None)
            self.setText(f"⚡ {fmt_power(watts)} · {fmt_kwh(total.wh)} {glyph}")
            self.setToolTip(QApplication.translate(
                "tilauscope_energy", "Power now and energy since monitoring started — {0}. Tap for details.").format(words))
            if colour != self._colour:
                self._colour = colour
                self.setStyleSheet(
                    f"QPushButton {{ background: {THEME['SURFACE']}; color: {THEME['TEXT']};"
                    f" border: 1px solid {colour}; border-radius: 13px; padding: 0 8px;"
                    f" font-family: 'JetBrains Mono', monospace; font-size: 11px; }}"
                    f"QPushButton:hover {{ background: {THEME['BORDER']}; }}")
            self.setVisible(True)
        except Exception as e:  # pylint: disable=broad-except
            _log.debug("energy pill: %s", e)


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
            text = (QApplication.translate("tilauscope_energy", "Roaster") if name == ROASTER
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
                label = (QApplication.translate("tilauscope_energy", "Roaster") if name == ROASTER
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
    """Non-modal sheet: live while monitoring, otherwise the loaded roast —
    or, with `profile`, one saved roast (BeanCave), never live."""

    def __init__(self, aw: Any, parent: QWidget | None = None, profile: dict | None = None) -> None:
        super().__init__(parent)
        self.aw = aw
        self._profile = profile
        self._profile_session = session_for_profile(profile) if profile is not None else None
        self._tap = ensure_energy_tap(aw)
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
        self._now = QLabel()
        self._now.setStyleSheet(_mono(18, 700, THEME['TEXT']))
        self._total = QLabel()
        self._total.setStyleSheet(_mono(13, 700, THEME['TEXT']))
        self._total.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        hero.addWidget(self._now)
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
                ("before", QApplication.translate("tilauscope_energy", "Preheat"),
                 QApplication.translate("tilauscope_energy", "From monitoring ON to CHARGE, including any wait before preheating."), 1),
                ("roast", QApplication.translate("tilauscope_energy", "Roast"),
                 QApplication.translate("tilauscope_energy", "From CHARGE to DROP."), 2),
                ("after", QApplication.translate("tilauscope_energy", "Cooling"),
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
            cells = [QLabel(_channel_label(name)), QLabel(), QLabel(), QLabel()]
            cells[1].setStyleSheet(_mono(11, 400, THEME['TEXT']))
            cells[2].setStyleSheet(_mono(11, 400, THEME['TEXT']))
            for c in (1, 2):
                cells[c].setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            for c, cell in enumerate(cells):
                self._rows.addWidget(cell, r, c)
            note = QLabel()
            note.setWordWrap(True)
            note.setStyleSheet(f"color: {THEME['SUBTEXT']}; font-size: 11px;")
            self._rows.addWidget(note, r + 1, 0, 1, 4)
            cells.append(note)
            self._cells[name] = cells
            r += 2
        self._rows.setColumnStretch(0, 1)
        root.addLayout(self._rows)

        self._setup_btn = QPushButton(QApplication.translate("tilauscope_energy", "Set up meter"))
        self._setup_btn.setProperty('variant', 'outline')
        self._setup_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._setup_btn.clicked.connect(self._open_setup)
        root.addWidget(self._setup_btn, 0, Qt.AlignmentFlag.AlignRight)

        self._per_kg = QLabel()
        self._coverage = QLabel()
        self._coverage.setWordWrap(True)
        self._coverage.setStyleSheet(f"color: {THEME['SUBTEXT']}; font-size: 11px;")
        root.addWidget(self._per_kg)
        root.addWidget(self._coverage)

        self._sources_btn = QPushButton(QApplication.translate("tilauscope_energy", "⚙ Sources"))
        self._sources_btn.setProperty('variant', 'ghost')
        self._sources_btn.setCheckable(True)
        self._sources_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sources_btn.toggled.connect(self._toggle_sources)
        root.addWidget(self._sources_btn, 0, Qt.AlignmentFlag.AlignRight)

        self._sources = QFrame()
        src = QVBoxLayout(self._sources)
        src.setContentsMargins(0, 0, 0, 0)
        src.setSpacing(4)
        self._src_line: dict[str, QLabel] = {}
        for name in (ROASTER, EXTRACTOR):
            lbl = QLabel()
            lbl.setWordWrap(True)
            lbl.setStyleSheet(f"color: {THEME['SUBTEXT']}; font-size: 11px;")
            src.addWidget(lbl)
            self._src_line[name] = lbl
        self._on_meter = QCheckBox(QApplication.translate("tilauscope_energy", "Extractor is plugged into the roaster meter"))
        self._on_meter.setToolTip(QApplication.translate(
            "tilauscope_energy", "Counts the extractor inside the roaster reading instead of adding it. "
                  "Applies from the next monitoring session, or now before START."))
        self._on_meter.setChecked(bool(QSettings().value(SETTING_EXTRACTOR_ON_ROASTER_METER, False, type=bool)))
        self._on_meter.toggled.connect(self._set_on_meter)
        src.addWidget(self._on_meter)
        self._sources.hide()
        root.addWidget(self._sources)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.refresh()

    # ── data ─────────────────────────────────────────────────────────────

    def _current(self) -> tuple[EnergySession | None, bool]:
        if self._profile is not None:
            return self._profile_session, False
        tap = self._tap
        if tap is not None and tap.live:
            return tap.session, True
        return getattr(self.aw.qmc, "tilau_energy", None), False

    def refresh(self) -> None:
        try:
            self._refresh()
        except Exception as e:  # pylint: disable=broad-except
            _log.debug("energy panel: %s", e)

    def _refresh(self) -> None:
        session, live = self._current()
        qmc = self.aw.qmc
        recording = live and bool(getattr(qmc, "flagstart", False))
        self._state.setText(
            QApplication.translate("tilauscope_energy", "Roasting") if recording
            else QApplication.translate("tilauscope_energy", "Monitoring") if live
            else QApplication.translate("tilauscope_energy", "Rebuilt from the saved curve")
            if session is not None and session.rebuilt
            else QApplication.translate("tilauscope_energy", "Saved roast") if session is not None
            else QApplication.translate("tilauscope_energy", "No energy data"))
        self._on_meter.setEnabled(not recording)
        self._timer.setInterval(1000 if live else 5000)
        self._refresh_sources()

        if session is None:
            self._now.setText("—")
            self._total.setText("")
            for key in ("before", "roast", "after"):
                self._phase[key].setText("—")
            for name, cells in self._cells.items():
                self._fill_row(name, cells, None, None, None, None)
            self._per_kg.setText("")
            self._coverage.setText(QApplication.translate(
                "tilauscope_energy", "This roast carries no energy record."))
            self._setup_btn.setVisible(self._profile is None)
            self._sources_btn.setVisible(self._profile is None)
            self._trace.set_data(None, None)
            return

        summary = (summarize_profile(self._profile, session) if self._profile is not None
                   else summarize_current(self.aw, session, live))
        self._trace.set_data(session, summary)
        now = time.time()
        power: float | None = None
        if live:
            for name in summary.expected:
                ch = session.channels.get(name)
                w = ch.power_now(now)[0] if ch is not None else None
                if w is not None:
                    power = (power or 0.0) + w
        self._now.setText(QApplication.translate("tilauscope_energy", "{0} now").format(fmt_power(power)) if live else "")
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
            names = {"drying": QApplication.translate("tilauscope_energy", "Drying"),
                     "maillard": QApplication.translate("tilauscope_energy", "Maillard"),
                     "development": QApplication.translate("tilauscope_energy", "Development")}
            self._phase["roast"].setToolTip("\n".join(
                f"{names[n]}  {fmt_kwh(summary.total(p.per_channel).wh)}" for n, p in summary.roast_split))
        else:
            self._phase["roast"].setToolTip("")

        for name, cells in self._cells.items():
            ch = session.channels.get(name)
            tot = summary.since_start.get(name)
            w = ch.power_now(now)[0] if (ch is not None and live) else None
            self._fill_row(name, cells, session, summary, tot, w)

        if summary.wh_per_kg is not None:
            self._per_kg.setText(QApplication.translate(
                "tilauscope_energy", "Roast energy per kg green   {0} kWh/kg").format(f"{summary.wh_per_kg / 1000:.3f}"))
        elif summary.roast is None or summary.roast.open:
            self._per_kg.setText(QApplication.translate(
                "tilauscope_energy", "Roast energy per kg green   — (after DROP)"))
        elif green_kg(self._profile.get("weight") if self._profile is not None else qmc.weight) <= 0:
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
        self._setup_btn.setVisible(live and self._needs_setup(summary))
        self._sources_btn.setVisible(self._profile is None)

    def _fill_row(self, name: str, cells: list[QLabel], session: EnergySession | None,
                  summary: Summary | None, tot: Totals | None, watts: float | None) -> None:
        included = summary is not None and name == EXTRACTOR and summary.extractor_included
        expected = summary is not None and (name in summary.expected or included)
        visible = name == ROASTER or expected or (session is not None and name in session.channels)
        for c in cells:
            c.setVisible(visible)
        if not visible:
            return
        cells[1].setVisible(session is not None and self._profile is None and self._tap is not None
                            and self._tap.live)   # "now" means nothing for a saved roast
        cells[1].setText(fmt_power(watts))
        cells[2].setText(fmt_kwh(tot.wh) if tot is not None and tot.provenance != NONE else "—")
        glyph, colour, words = provenance(tot)
        if included:
            words = QApplication.translate("tilauscope_energy", "Included in roaster meter")
        cells[3].setText(f"{glyph} {words}")
        cells[3].setStyleSheet(f"color: {colour}; font-size: 11px;")
        note = ""
        if tot is None or tot.provenance == NONE:
            if name == ROASTER and not included:
                note = QApplication.translate(
                    "tilauscope_energy", 'No power model for this roaster. Add an MQTT power sensor named '
                          '"roaster" to measure it.')
        elif tot.incomplete:
            note = QApplication.translate(
                "tilauscope_energy", "Meter silent for {0} s in all — that time is left out.").format(f"{tot.unknown_s:.0f}")
        elif tot.provenance in (ESTIMATED, MIXED):
            note = QApplication.translate(
                "tilauscope_energy", "Estimated from the rated power and the burner setting.")
        cells[4].setText(note)
        cells[4].setVisible(bool(note))

    def _refresh_sources(self) -> None:
        tap = self._tap
        for name, lbl in self._src_line.items():
            status = tap.status.get(name, MISSING) if tap is not None else MISSING
            label = _channel_label(name)
            if status == OK and tap is not None:
                sensor = tap.sensor(name)
                seen = tap.last_arrival(name)
                age = (QApplication.translate("tilauscope_energy", "last reading {0} s ago").format(f"{time.time() - seen:.0f}")
                       if seen is not None else QApplication.translate("tilauscope_energy", "no reading yet"))
                topic = sensor.topic if sensor is not None else ""
                lbl.setText(f"{label} — {topic} · W · {age}")
            elif status == DUPLICATE:
                lbl.setText(QApplication.translate("tilauscope_energy", '{0} — two sensors are named "{1}": keep one.').format(label, name))
            elif status == UNIT:
                lbl.setText(QApplication.translate("tilauscope_energy", '{0} — sensor "{1}" is not set to W: unit not confirmed.').format(label, name))
            else:
                lbl.setText(QApplication.translate("tilauscope_energy", '{0} — no MQTT sensor named "{1}".').format(label, name))

    # ── actions ──────────────────────────────────────────────────────────

    def _toggle_sources(self, shown: bool) -> None:
        self._sources.setVisible(shown)
        self.adjustSize()

    def _set_on_meter(self, checked: bool) -> None:
        QSettings().setValue(SETTING_EXTRACTOR_ON_ROASTER_METER, checked)
        tap = self._tap
        if tap is not None and tap.live and tap.session is not None \
                and not bool(getattr(self.aw.qmc, "flagstart", False)):
            tap.session.extractor_on_roaster_meter = checked
        self.refresh()

    def _needs_setup(self, summary: Summary) -> bool:
        """A source the operator expects is not usable as configured."""
        tap = self._tap
        if tap is None:
            return True
        names = [ROASTER] + ([EXTRACTOR] if EXTRACTOR in summary.expected or summary.extractor_included else [])
        return any(tap.status.get(n, MISSING) != OK for n in names)

    def _open_setup(self) -> None:
        """Straight to the MQTT sensor table, scrolled into view, with the first
        reserved sensor that still needs its unit selected: its one-tap pills
        show under the table."""
        try:
            from PyQt6.QtWidgets import QScrollArea
            from tilauscope.devices import TilauscopeConfigDlg
            dlg = TilauscopeConfigDlg(self.aw, self.aw)
            dlg._tabs.setCurrentWidget(dlg._integrations_tab)   # pylint: disable=protected-access
            table = dlg.mqtt_sensor_table
            for row in range(table.rowCount()):
                item = table.item(row, 0)
                name = item.text().strip().lower() if item is not None else ""
                unit = table.cellWidget(row, 5)
                if name in (ROASTER, EXTRACTOR) and getattr(unit, "currentData", lambda: "")() != "W":
                    table.setCurrentCell(row, 0)   # current, so the power pills show
                    break
            dlg.show()

            def _reveal() -> None:
                w = table.parentWidget()
                while w is not None and not isinstance(w, QScrollArea):
                    w = w.parentWidget()
                if w is not None:
                    w.ensureWidgetVisible(table, 0, 40)
            QTimer.singleShot(0, _reveal)
        except Exception as e:  # pylint: disable=broad-except
            _log.warning("energy: opening the meter setup failed: %s", e)

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

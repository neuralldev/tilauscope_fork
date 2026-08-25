#
# ABOUT
# Roast Review: the left panel of TilauScope while a finished roast is displayed.

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

"""What the left panel shows when there is nothing to steer.

While a roast is recording the panel carries the machine controls; once it is
over — or once a past roast is opened from a file — those controls are inert,
and this page takes their place: what the roast did, and how it compares to the
plan frozen before it. Every word of the verdict comes from `roast_debrief`,
never from this file, so the panel and the roast card can never disagree.

Built once per switch, never in the sampling path.
"""

import logging
from typing import Final

from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QFrame, QGridLayout, QPushButton)
from PyQt6.QtCore import Qt, QRectF, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath

from artisanlib.util import convertRoRstrict
from tilauscope.tilauscope_types import THEME
from tilauscope.theme_qss import base_qss, tooltip_qss
from tilauscope.roast_debrief import (build_debrief, profile_from_qmc, fmt_mmss,
                                      display_name, Debrief)

_log: Final[logging.Logger] = logging.getLogger(__name__)

# Phase colours, matching the phase blocks of the control panel.
_PHASE_COLOR: Final[dict[str, str]] = {
    "dry": THEME['ACCENT'], "mai": THEME['YELLOW'], "dev": THEME['WARNING']}

_SEVERITY_COLOR: Final[dict[str, str]] = {
    "ok": THEME['SUCCESS'], "attention": THEME['YELLOW'],
    "neutral": THEME['TEXT'], "none": THEME['BORDER']}


def _mono(size: int, weight: int = 400, color: str = "") -> str:
    col = f" color: {color};" if color else ""
    return (f"font-family: 'JetBrains Mono', monospace; font-size: {size}px;"
            f" font-weight: {weight};{col} background: transparent; border: none;")


class RoastReviewPanel(QWidget):
    """Read-only summary of the roast currently on screen."""

    card_requested = pyqtSignal()
    weight_requested = pyqtSignal()

    def __init__(self, aw, parent=None):
        super().__init__(parent)
        self.aw = aw
        self.setStyleSheet(base_qss() + f"""
            QWidget {{ background: transparent; }}
            QLabel {{ color: {THEME['TEXT']}; background: transparent; border: none; }}
        """)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 4, 0, 0)
        self._lay.setSpacing(6)
        self._empty = True

    # ── public API ────────────────────────────────────────────────────────

    def refresh(self) -> None:
        """Rebuild the page from whatever roast is currently loaded.

        Called on STOP and on profile load only — never from the update slot.
        Guarded whole: a malformed profile must not take the window down.
        """
        try:
            self._clear()
            profile = profile_from_qmc(self.aw)
            snapshot = getattr(self.aw.qmc, "tilau_roast_plan_snapshot", None)
            # The live Artisan unit is the display authority. profile_from_qmc
            # normally carries the same value, but qmc.mode also covers a
            # profile converted after it was loaded.
            mode = str(getattr(self.aw.qmc, "mode", "C") or "C").upper()
            if mode not in {"C", "F"}:
                mode = "C"
            debrief = build_debrief(
                profile, snapshot, mode,
                peak_ror_reference_c=self._peak_ror_reference(),
                peak_ror_c=self._peak_ror())
            self._profile = profile
            self._build(profile, debrief, mode)
            self._empty = False
        except Exception as e:  # pylint: disable=broad-except
            _log.exception(e)
            self._clear()
            lbl = QLabel(QApplication.translate(
                "tilauscope_review", "This roast could not be read."))
            lbl.setWordWrap(True)
            lbl.setStyleSheet(f"color: {THEME['SUBTEXT']};")
            self._lay.addWidget(lbl)
            self._lay.addStretch(1)

    def has_roast(self) -> bool:
        """True when a roast with a CHARGE and a DROP is on screen."""
        try:
            ti = self.aw.qmc.timeindex
            return bool(ti and ti[0] > -1 and len(ti) > 6 and ti[6] > 0)
        except Exception:  # pylint: disable=broad-except
            return False

    # ── data the panel has to work out for itself ─────────────────────────

    def _peak_ror(self) -> "float | None":
        """Peak BT rate of rise, recomputed here rather than read.

        The RoR is never stored in the .alog and Artisan only rebuilds it at
        load time when DeltaBT is ticked, so the panel cannot depend on that
        box. The result stays local: qmc.delta2 is left exactly as the user
        chose to display it.
        """
        try:
            qmc = self.aw.qmc
            timex = qmc.timex
            if not timex or len(timex) < 3:
                return None
            bt = qmc.stemp2 if getattr(qmc, "stemp2", None) else qmc.temp2
            if not bt or len(bt) != len(timex):
                bt = qmc.temp2
            if not bt or len(bt) != len(timex):
                return None
            _, delta_bt = qmc.recomputeDeltas(
                timex, qmc.timeindex[0], qmc.timeindex[6], None, bt,
                optimalSmoothing=getattr(qmc, "optimalSmoothing", True))
            if not delta_bt:
                return None
            # Before the turning point the BT is still falling into the drum;
            # the peak that means anything is the one after it.
            start = int(getattr(qmc, "TPalarmtimeindex", -1) or -1)
            if start < 0:
                start = qmc.timeindex[0] if qmc.timeindex[0] > -1 else 0
            values = [v for v in delta_bt[start:] if v is not None]
            if not values:
                return None
            # recomputeDeltas follows qmc.mode. Debrief inputs are canonical
            # °C/min so they can be rendered consistently in either unit.
            mode = str(getattr(qmc, "mode", "C") or "C").upper()
            if mode not in {"C", "F"}:
                mode = "C"
            return convertRoRstrict(float(max(values)), mode, "C")
        except Exception as e:  # pylint: disable=broad-except
            _log.debug("peak RoR: %s", e)
            return None

    def _peak_ror_reference(self) -> "float | None":
        try:
            from tilauscope.roasters import RoasterManager
            ctx = RoasterManager().get_roast_context(self.aw.tilau_roaster)
            return getattr(ctx, "peak_ror_reference_c", None)
        except Exception as e:  # pylint: disable=broad-except
            _log.debug("roaster context: %s", e)
            return None

    # ── construction ──────────────────────────────────────────────────────

    def _clear(self) -> None:
        self._drop_children(self._lay)

    def _drop_children(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
                continue
            child = item.layout()
            if child is not None:
                # Nested layouts (the action row) own no widget of their own and
                # would survive the rebuild, stacking a second row of buttons.
                self._drop_children(child)
                child.deleteLater()

    def _build(self, profile: dict, debrief: Debrief, mode: str) -> None:
        self._lay.addWidget(self._header(profile, debrief))
        self._lay.addWidget(self._verdict(debrief))
        bar = self._phase_bar(debrief)
        if bar is not None:
            self._lay.addWidget(bar)
        table = self._milestones(debrief, mode)
        if table is not None:
            self._lay.addWidget(table)
        self._lay.addWidget(self._figures(debrief))
        if debrief.figures.get("weight_loss") and debrief.figures["weight_loss"].value == "—":
            self._lay.addWidget(self._weight_prompt())
        for strip in self._strips(profile, mode):
            self._lay.addWidget(strip)
        self._lay.addStretch(1)
        self._lay.addWidget(self._card_button())

    def _header(self, profile: dict, debrief: Debrief) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        ident = QVBoxLayout()
        ident.setContentsMargins(0, 0, 0, 0)
        ident.setSpacing(2)

        title = display_name(profile)
        name = QLabel(title.upper() or QApplication.translate("tilauscope_review", "ROAST"))
        name.setWordWrap(True)
        name.setStyleSheet(f"font-size: 13px; font-weight: 800; color: {THEME['ACCENT']};")
        ident.addWidget(name)

        bits = [b for b in (str(profile.get("roastdate") or "").strip(),
                            str(profile.get("roasttime") or "").strip()[:5]) if b]
        batch_nr = int(profile.get("roastbatchnr") or 0)
        if batch_nr:
            bits.append(f"{profile.get('roastbatchprefix') or ''}#{batch_nr}")
        sub = QLabel(" · ".join(bits))
        sub.setStyleSheet(_mono(10, 400, THEME['OVERLAY0']))
        ident.addWidget(sub)
        top.addLayout(ident, 1)

        # "Incomplete" means a figure the roast should carry is missing —
        # typically the roasted weight or the colour, both entered after DROP.
        state_ok = all(f.value != "—" for f in debrief.figures.values())
        chip = QLabel(QApplication.translate("tilauscope_review", "FINISHED") if state_ok
                      else QApplication.translate("tilauscope_review", "INCOMPLETE"))
        col = THEME['SUCCESS'] if state_ok else THEME['YELLOW']
        chip.setStyleSheet(_mono(9, 700, col) + f"border: 1px solid {col};"
                           f" border-radius: 8px; padding: 1px 7px;")
        top.addWidget(chip, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(top)

        # The plan badge says outright whether a comparison is possible at all.
        if debrief.has_plan:
            badge_txt = QApplication.translate("tilauscope_review", "COMPARED TO THE ROAST PLAN")
            badge_col = THEME['MAUVE']
        else:
            badge_txt = QApplication.translate("tilauscope_review", "NO PLAN RECORDED")
            badge_col = THEME['OVERLAY0']
        badge = QLabel(badge_txt)
        badge.setStyleSheet(_mono(9, 700, badge_col) + f"border: 1px solid {badge_col};"
                            f" border-radius: 8px; padding: 1px 7px;")
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(badge)
        row.addStretch(1)
        lay.addLayout(row)
        return box

    def _verdict(self, debrief: Debrief) -> QWidget:
        frame = QFrame()
        accent = _SEVERITY_COLOR.get(debrief.severity, THEME['BORDER'])
        frame.setStyleSheet(
            f"QFrame {{ background: {THEME['SURFACE']};"
            f" border: 1px solid {THEME['BORDER']};"
            f" border-left: 3px solid {accent}; border-radius: 8px; }}"
            f"QLabel {{ border: none; background: transparent; }}")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(9, 7, 9, 7)
        lay.setSpacing(2)

        text = debrief.headline
        if debrief.detail:
            text = f"<b>{debrief.headline}</b> {debrief.detail}"
        else:
            text = f"<b>{debrief.headline}</b>"
        head = QLabel(text)
        head.setWordWrap(True)
        head.setTextFormat(Qt.TextFormat.RichText)
        head.setStyleSheet("font-size: 12px;")
        lay.addWidget(head)

        if debrief.next_time:
            nxt = QLabel(debrief.next_time)
            nxt.setWordWrap(True)
            nxt.setStyleSheet(f"font-size: 11px; color: {THEME['SUBTEXT']};")
            lay.addWidget(nxt)
        return frame

    def _phase_bar(self, debrief: Debrief) -> "QWidget | None":
        total = sum(debrief.phases.values())
        if total <= 0:
            return None
        # Each phase name is passed to translate() as a literal: the string
        # extractor cannot see a name held in a loop variable.
        names = {"dry": QApplication.translate("tilauscope_review", "DRY"),
                 "mai": QApplication.translate("tilauscope_review", "MAI"),
                 "dev": QApplication.translate("tilauscope_review", "DEV")}
        segments = [(names[key], debrief.phases[key],
                     debrief.phases[key] / total * 100.0, _PHASE_COLOR[key])
                    for key in ("dry", "mai", "dev") if debrief.phases.get(key)]
        return _PhaseRibbon(segments)

    def _milestones(self, debrief: Debrief, mode: str) -> "QWidget | None":
        if not debrief.milestones:
            return None
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background: {THEME['SURFACE']};"
            f" border: 1px solid {THEME['BORDER']}; border-radius: 8px; }}"
            f"QLabel {{ border: none; background: transparent; }}")
        grid = QGridLayout(frame)
        grid.setContentsMargins(9, 5, 9, 5)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(1)

        # Fourth column is the deviation from the plan when there is one, and
        # the rate of rise at the milestone when there is not.
        last_col = (QApplication.translate("tilauscope_review", "VS PLAN")
                    if debrief.has_plan else "")
        for col, text in enumerate((QApplication.translate("tilauscope_review", "MILESTONE"),
                                    QApplication.translate("tilauscope_review", "TIME"),
                                    f"BT °{mode}", last_col)):
            head = QLabel(text)
            head.setStyleSheet(_mono(9, 700, THEME['OVERLAY0']))
            head.setAlignment(Qt.AlignmentFlag.AlignLeft if col == 0
                              else Qt.AlignmentFlag.AlignRight)
            grid.addWidget(head, 0, col)

        colours = {"CHARGE": THEME['SUCCESS'], "TP": THEME['TEAL'],
                   "DRY END": THEME['ACCENT'], "FC START": THEME['WARNING'],
                   "DROP": THEME['CRITICAL']}
        delta_key = {"DRY END": "dry_end", "FC START": "first_crack", "DROP": "drop"}
        for row, (key, seconds, bt) in enumerate(debrief.milestones, start=1):
            name = QLabel(key)
            name.setStyleSheet(_mono(9, 700, colours.get(key, THEME['TEXT'])))
            grid.addWidget(name, row, 0)
            for col, text in ((1, fmt_mmss(seconds)), (2, f"{bt:.1f}")):
                val = QLabel(text)
                val.setStyleSheet(_mono(10, 400, THEME['TEXT']))
                val.setAlignment(Qt.AlignmentFlag.AlignRight)
                grid.addWidget(val, row, col)
            grid.addWidget(self._delta_label(debrief, delta_key.get(key), mode), row, 3)
        return frame

    def _delta_label(self, debrief: Debrief, key: "str | None", mode: str) -> QLabel:
        text, colour = "—", THEME['OVERLAY0']
        delta = debrief.deltas.get(key) if key else None
        if delta is not None:
            # The drop is judged on temperature — that is how it is steered —
            # and the earlier milestones on the clock.
            if key == "drop" and delta.bt_c is not None:
                text = f"{delta.bt_c:+.0f} °{mode}"
                colour = THEME['SUCCESS'] if abs(delta.bt_c) < 3.0 else THEME['YELLOW']
            elif delta.time_s is not None:
                text = f"{delta.time_s:+.0f} s"
                colour = THEME['SUCCESS'] if abs(delta.time_s) < 30.0 else THEME['YELLOW']
        lbl = QLabel(text)
        lbl.setStyleSheet(_mono(10, 400, colour))
        lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        return lbl

    def _figures(self, debrief: Debrief) -> QWidget:
        box = QWidget()
        grid = QGridLayout(box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)
        cells = (("dtr", QApplication.translate("tilauscope_review", "DEVELOPMENT")),
                 ("dev_rise", QApplication.translate("tilauscope_review", "DEV RISE")),
                 ("peak_ror", QApplication.translate("tilauscope_review", "PEAK RoR")),
                 ("weight_loss", QApplication.translate("tilauscope_review", "WEIGHT LOSS")))
        for i, (key, label) in enumerate(cells):
            fig = debrief.figures.get(key)
            grid.addWidget(self._cell(label, fig), i // 2, i % 2)
        return box

    def _cell(self, label: str, fig) -> QWidget:
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background: {THEME['SURFACE']};"
            f" border: 1px solid {THEME['BORDER']}; border-radius: 8px; }}"
            f"QLabel {{ border: none; background: transparent; }}")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(8, 5, 8, 5)
        lay.setSpacing(0)
        cap = QLabel(label)
        cap.setStyleSheet(_mono(9, 400, THEME['OVERLAY0']))
        lay.addWidget(cap)
        text = fig.value if fig else "—"
        value = QLabel(text)
        # A value that was never measured is not a neutral reading: it is muted
        # so the eye does not read it as a figure.
        colour = (THEME['OVERLAY0'] if text == "—"
                  else _SEVERITY_COLOR.get(fig.severity if fig else "neutral", THEME['TEXT']))
        value.setStyleSheet(_mono(15, 800, colour))
        lay.addWidget(value)
        band = QLabel(fig.band if fig else "")
        band.setWordWrap(True)
        band.setStyleSheet(f"font-size: 9px; color: {THEME['OVERLAY2']};")
        lay.addWidget(band)
        return frame

    def _weight_prompt(self) -> QWidget:
        """The one missing value the operator can still fix, right now."""
        btn = QPushButton("⚖  " + QApplication.translate(
            "tilauscope_review", "Weigh the roasted beans to get the loss"))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {THEME['YELLOW']};"
            f" border: 1px dashed {THEME['YELLOW']}; border-radius: 8px;"
            f" padding: 5px 9px; font-size: 11px; text-align: left; }}"
            f"QPushButton:hover {{ background: {THEME['SURFACE']}; }}" + tooltip_qss())
        btn.setToolTip(QApplication.translate(
            "tilauscope_review", "Opens the roast properties on the weight field"))
        btn.clicked.connect(self.weight_requested.emit)
        return btn

    def _strips(self, profile: dict, mode: str) -> list[QWidget]:
        out: list[QWidget] = []
        w = profile.get("weight") or []
        if len(w) >= 3:
            unit = str(w[2] or "g")
            w_in, w_out = w[0] or 0, w[1] or 0
            if w_in:
                bits = [(QApplication.translate("tilauscope_review", "GREEN"),
                         f"{float(w_in):g} {unit}")]
                bits.append((QApplication.translate("tilauscope_review", "ROASTED"),
                             f"{float(w_out):g} {unit}" if w_out else "—"))
                out.append(self._strip(bits))
        # Ambient is dropped entirely rather than shown at its defaults: a
        # figure nobody measured is worse than no figure.
        amb = [(QApplication.translate("tilauscope_review", "ROOM"),
                f"{float(profile.get('ambientTemp') or 0):.1f} °{mode}"
                if profile.get("ambientTemp") else None),
               (QApplication.translate("tilauscope_review", "RH"),
                f"{float(profile.get('ambient_humidity') or 0):.0f} %"
                if profile.get("ambient_humidity") else None),
               (QApplication.translate("tilauscope_review", "PRESSURE"),
                f"{float(profile.get('ambient_pressure') or 0):.0f} hPa"
                if profile.get("ambient_pressure") else None)]
        amb = [(k, v) for k, v in amb if v]
        if amb:
            out.append(self._strip(amb))
        return out

    def _strip(self, bits: list) -> QWidget:
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background: {THEME['SURFACE']};"
            f" border: 1px solid {THEME['BORDER']}; border-radius: 8px; }}"
            f"QLabel {{ border: none; background: transparent; }}")
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(6)
        for i, (key, value) in enumerate(bits):
            if i:
                lay.addStretch(1)
            lbl = QLabel(f"{key} ")
            lbl.setStyleSheet(_mono(10, 400, THEME['OVERLAY0']))
            lay.addWidget(lbl)
            val = QLabel(value)
            val.setStyleSheet(_mono(10, 700, THEME['TEXT']))
            lay.addWidget(val)
        return frame

    def _card_button(self) -> QPushButton:
        """The only action here: the same reading with the curve on it."""
        card = QPushButton(QApplication.translate("tilauscope_review", "Full roast card"))
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {THEME['ACCENT']};"
            f" border: 1px solid {THEME['ACCENT']}; border-radius: 13px;"
            f" padding: 5px 10px; font-size: 11px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {THEME['SURFACE']}; }}")
        card.clicked.connect(self.card_requested.emit)
        return card


class _PhaseRibbon(QWidget):
    """Drying, Maillard and development as one bar cut into three.

    Painted rather than laid out: only the paint pass knows how wide a segment
    actually ended up, which is what decides how much of its caption can be
    shown. A caption that does not fit is shortened — never clipped, and never
    solved by shrinking the type past the point where it can be read at arm's
    length.
    """

    _HEIGHT = 22
    _RADIUS = 5.0

    def __init__(self, segments: list, parent=None):
        super().__init__(parent)
        self._segments = segments
        self.setFixedHeight(self._HEIGHT)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

    def paintEvent(self, event) -> None:  # noqa: N802  (Qt override)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Round the bar as a whole, then paint the segments inside it.
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), self._RADIUS, self._RADIUS)
        painter.setClipPath(clip)

        font = QFont("JetBrains Mono")
        font.setPixelSize(11)
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        metrics = QFontMetrics(font)

        total = sum(pct for _, _, pct, _ in self._segments) or 100.0
        x = 0.0
        width = float(self.width())
        for i, (label, seconds, pct, colour) in enumerate(self._segments):
            # The last segment takes the rounding slack so the bar always ends
            # flush with its own right edge.
            w = (width - x) if i == len(self._segments) - 1 else width * pct / total
            rect = QRectF(x, 0.0, w, float(self.height()))
            painter.fillRect(rect, QColor(colour))

            # Longest caption that fits, in decreasing order of usefulness.
            for text in (f"{label} {fmt_mmss(seconds)} · {pct:.0f} %",
                         f"{label} {fmt_mmss(seconds)}",
                         f"{label} {pct:.0f} %",
                         f"{pct:.0f} %",
                         label, ""):
                if not text or metrics.horizontalAdvance(text) <= w - 8:
                    break
            if text:
                painter.setPen(QColor(THEME['CRUST']))
                painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), text)
            x += w
        painter.end()

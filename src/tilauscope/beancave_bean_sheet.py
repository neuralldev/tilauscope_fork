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
# Tilau 2025-2026

"""Read-first bean sheet for BeanCave, in two columns sized to fit a 600 px window:
ESSENTIALS and ROAST MEMORY on the left; CHARACTERISTICS, PROVENANCE and the
sacks line on the right. Each zone's ✎ Edit button emits ``editRequested(zone_key)``;
the sheet itself never writes anything.
"""

from __future__ import annotations

import logging
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from tilauscope.bean_energy import match_variety_family
from tilauscope.bean_qualifiers import physical_qualifier, screen_size_label
from tilauscope.beancave_catalogue import short_date, svg_pixmap
from tilauscope.roast_memory import RoastMemory, ready_to_taste
from tilauscope.sack_manager import SackChipsRow
from tilauscope.theme_qss import tint
from tilauscope.tilauscope_types import THEME, format_money
from tilauscope.widgets.flow_layout import FlowLayout

_logd = logging.getLogger('tilau')

_MONO = "'JetBrains Mono', monospace"
_DIM = THEME['OVERLAY0']
_PLAIN = "background:transparent;border:none;"

# Blend bar segments, one colour per component.
_BLEND_COLOURS = (THEME['ACCENT'], THEME['TEAL'], THEME['PINK'])

# Density of the sheet: 1.0 keeps it whole in a 600 px window; with more room
# it grows, up to _MAX_K, until it fills the height. Set before each build.
_K = 1.0
_MAX_K = 1.6
_MAX_FONT_K = 1.15


def _px(n: float) -> int:
    """A spacing or a margin at the current density."""
    return round(n * _K)


def _fs(n: float) -> int:
    """A font size: the room goes to the spacing, the text grows only a little,
    so the sheet still reads as part of the same window as the catalogue."""
    return round(n * min(_K, _MAX_FONT_K))

_SVG_PLACE = "M12 21s-6-5.5-6-10a6 6 0 0 1 12 0c0 4.5-6 10-6 10zM12 9a2 2 0 1 0 0 4a2 2 0 1 0 0-4"
_SVG_ALTITUDE = "M3 19l6-10 4 6 2-3 6 7z"
_SVG_SUPPLIER = "M3 7h11v9H3zM14 10h4l3 3v3h-7M7 16a1.5 1.5 0 1 0 0 3a1.5 1.5 0 1 0 0-3M17 16a1.5 1.5 0 1 0 0 3a1.5 1.5 0 1 0 0-3"
_SVG_PRICE = "M3 12l9-9h7v7l-9 9zM15.5 7a1 1 0 1 0 0 .01"
_SVG_LEAF = "M12 21v-9M12 12c0-4 3-6 7-6 0 4-3 6-7 6zM12 14c0-3-2.5-5-6-5 0 3 2.5 5 6 5z"
_SVG_CUP = "M5 8h11v6a5 5 0 0 1-5 5h-1a5 5 0 0 1-5-5zM16 10h2a2 2 0 0 1 0 4h-2"
_SVG_BULB = ("M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2.1h5c0-.9.4-1.6 "
             "1-2.1A6 6 0 0 0 12 3z")


def _icon(path_d: str, colour: str, size: int = 15) -> QLabel:
    """A stroked 24-unit SVG path as a fixed-size label."""
    lbl = QLabel()
    lbl.setPixmap(svg_pixmap(path_d, colour, size, 1.8))
    lbl.setFixedSize(size, size)
    lbl.setStyleSheet(_PLAIN)
    return lbl


def _label(text: str, css: str, wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(css + _PLAIN)
    lbl.setWordWrap(wrap)
    return lbl


def _chip(text: str, filled: str | None = None) -> QLabel:
    """A rounded word; `filled` paints it in that colour for the one chip that leads."""
    if filled:
        css = (f"color:{THEME['BG']};background:{filled};font-size:{_fs(11)}px;font-weight:600;"
               f"border:none;border-radius:10px;padding:{_px(2)}px {_px(9)}px;")
    else:
        css = (f"color:{THEME['TEXT']};background:transparent;font-size:{_fs(11)}px;"
               f"border:1px solid {THEME['BORDER']};border-radius:10px;padding:{_px(1)}px {_px(9)}px;")
    lbl = QLabel(text)
    lbl.setStyleSheet(css)
    return lbl


class _Zone(QFrame):
    """Titled surface card with an optional ✎ Edit button."""

    def __init__(self, title: str, parent: QWidget | None = None, accent: bool = False) -> None:
        super().__init__(parent)
        border = tint('ACCENT', 0.55) if accent else THEME['BORDER']
        self.setStyleSheet(
            f"_Zone {{ background:{THEME['SURFACE']};"
            f"border:1px solid {border};border-radius:10px; }}")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(_px(14), _px(8), _px(14), _px(10))
        self.body.setSpacing(_px(6))

        self.head = QHBoxLayout()
        t = QLabel(title.upper())
        t.setStyleSheet(
            f"color:{THEME['ACCENT'] if accent else _DIM};font-size:{_fs(10)}px;"
            f"{'font-weight:600;' if accent else ''}letter-spacing:2px;" + _PLAIN)
        self.head.addWidget(t, 1)
        self.edit_btn = QPushButton("✎ " + QApplication.translate("Menu", "Edit"))
        self.edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.edit_btn.setStyleSheet(_link_css())
        self.head.addWidget(self.edit_btn)
        self.body.addLayout(self.head)


def _link_css() -> str:
    return (f"QPushButton {{ color:{THEME['ACCENT']};background:transparent;"
            f"border:1px solid transparent;border-radius:7px;"
            f"padding:2px 9px;font-size:{_fs(11)}px; }}"
            f"QPushButton:hover {{ border:1px solid {THEME['ACCENT']};"
            f"background:{tint('ACCENT', 0.08)}; }}")


class BeanSheetWidget(QWidget):
    """Read-only sheet in two columns; rebuilt on ``set_bean``."""

    editRequested = pyqtSignal(str)     # noqa: N815 — 'essentials'|'provenance'|'characteristics'|'sensory'
    sackReleased = pyqtSignal(str)      # noqa: N815 — re-emitted from the chips row
    tasteRequested = pyqtSignal(str)    # noqa: N815 — roastUUID of the roast to taste
    allRoastsRequested = pyqtSignal()   # noqa: N815
    newCropRequested = pyqtSignal()     # noqa: N815

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        # Sized to fit whole from a 600 px window; the scroll only rescues a
        # window shrunk below that.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"QScrollArea {{ background:{THEME['BG']};border:none; }}")
        self._host = QWidget()
        self._host.setStyleSheet(f"background:{THEME['BG']};")
        cols = self._cols = QHBoxLayout(self._host)
        cols.setContentsMargins(_px(12), _px(10), _px(12), _px(10))
        cols.setSpacing(_px(10))
        self._left = QVBoxLayout()
        self._right = QVBoxLayout()
        for col in (self._left, self._right):
            col.setSpacing(_px(10))
            col.addStretch(1)
            cols.addLayout(col, 1)
        scroll.setWidget(self._host)
        root.addWidget(scroll)
        self._zones: list[tuple[QVBoxLayout, QWidget]] = []
        self._k = 1.0
        self._last: tuple | None = None
        self._scroll = scroll
        self._refit = QTimer(self)
        self._refit.setSingleShot(True)
        self._refit.setInterval(120)
        self._refit.timeout.connect(self._fit)

    def resizeEvent(self, event) -> None:  # noqa: N802, ANN001
        super().resizeEvent(event)
        self._refit.start()

    def _fit(self) -> None:
        """Grow the density until the taller column fills the height, within _MAX_K."""
        if self._last is None:
            return
        self._build(1.0)
        # Measured before the first paint: style sheets have to be applied first,
        # or every label reports the default font and the sheet reads too short.
        for w in self._host.findChildren(QWidget):
            w.ensurePolished()
        self._cols.activate()
        width = self._scroll.viewport().width()
        need = self._cols.totalHeightForWidth(width) if width > 0 else -1
        if need < 0:   # no height-for-width answer yet: the plain hint will do
            need = self._host.sizeHint().height()
        room = self._scroll.viewport().height()
        k = 1.0
        if need > 0 and room > need:
            k = min(_MAX_K, round(room * 0.94 / need * 20) / 20)
        if k > 1.0:
            self._build(k)

    # ── public API ───────────────────────────────────────────────────────────
    def clear(self) -> None:
        for col, z in self._zones:
            col.removeWidget(z)
            z.hide()
            z.deleteLater()
        self._zones = []

    def set_bean(self, bean, memory: RoastMemory | None = None, mode: str = 'C') -> None:
        self._last = (bean, memory, mode)
        self._fit()

    def _build(self, k: float) -> None:
        global _K  # noqa: PLW0603 — read by the builders below, GUI thread only
        _K = self._k = k
        bean, memory, mode = self._last
        self._cols.setContentsMargins(_px(12), _px(10), _px(12), _px(10))
        self._cols.setSpacing(_px(10))
        for col in (self._left, self._right):
            col.setSpacing(_px(10))
        self.clear()
        try:
            self._build_essentials(bean, memory)
            self._build_memory(memory, mode)
            self._build_characteristics(bean)
            self._build_provenance(bean)
            self._build_sacks(bean)
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _logd.exception("bean sheet render failed")

    # ── zones ────────────────────────────────────────────────────────────────
    def _add(self, col: QVBoxLayout, zone: QWidget) -> None:
        col.insertWidget(sum(1 for c, _ in self._zones if c is col), zone)
        # A layout shows a new child on the next event loop turn; the fit
        # measures right away, and a hidden zone counts for nothing.
        zone.show()
        self._zones.append((col, zone))

    def _tile(self, value: str, caption: str, colour: str, border: str | None = None) -> QFrame:
        t = QFrame()
        t.setObjectName("sheetTile")
        t.setStyleSheet(
            f"QFrame#sheetTile {{ background:{tint('WARNING', 0.06) if border else THEME['BG']};"
            f"border:1px solid {border or THEME['BORDER']};border-radius:8px; }}")
        tl = QVBoxLayout(t)
        tl.setContentsMargins(_px(10), _px(5), _px(10), _px(5))
        tl.setSpacing(0)
        tl.addWidget(_label(value, f"color:{colour};font-family:{_MONO};font-size:{_fs(15)}px;font-weight:700;"))
        tl.addWidget(_label(caption.upper(), f"color:{border or _DIM};font-size:{_fs(9)}px;letter-spacing:1px;",
                            wrap=True))
        return t

    def _tiles_row(self, tiles: list[QFrame]) -> QGridLayout:
        g = QGridLayout()
        g.setHorizontalSpacing(8)
        for i, t in enumerate(tiles):
            g.addWidget(t, 0, i)
            g.setColumnStretch(i, 1)
        return g

    def _build_essentials(self, bean, memory: RoastMemory | None) -> None:
        z = _Zone(QApplication.translate("tilauscope_common", "Essentials"))
        z.edit_btn.setToolTip(QApplication.translate("tilauscope_beancave", "Edit name, origin, year and stock"))
        z.edit_btn.clicked.connect(lambda: self.editRequested.emit('essentials'))

        name_row = QHBoxLayout()
        name_row.setSpacing(_px(8))
        name_row.addWidget(_label(bean.name or "—",
                                  f"color:{THEME['TEXT']};font-size:{_fs(18)}px;font-weight:700;", wrap=True), 1)
        if getattr(bean, 'is_blend', False):
            b = QLabel(QApplication.translate("tilauscope_beancave", "BLEND"))
            b.setStyleSheet(
                f"color:{THEME['ACCENT']};font-size:{_fs(9)}px;font-weight:700;letter-spacing:1px;"
                f"border:1px solid {THEME['ACCENT']};border-radius:4px;padding:1px 6px;background:transparent;")
            name_row.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
        z.body.addLayout(name_row)

        sub_parts = [p for p in (bean.country, bean.process, bean.supplier) if p]
        z.body.addWidget(_label(" · ".join(sub_parts) if sub_parts else "—",
                                f"color:{THEME['SUBTEXT']};font-size:{_fs(12)}px;", wrap=True))

        stock = float(getattr(bean, 'weight_left', 0.0) or 0.0)
        batch = memory.weight_in_g if memory is not None else 0.0
        if batch > 0 and stock > 0:
            stock_caption = QApplication.translate("tilauscope_beancave", "≈ {0} batches").format(
                max(1, round(stock / batch)) if stock >= batch / 2 else 0)
        else:
            stock_caption = QApplication.translate("Label", "Stock")
        stock_tile = self._tile(f"{stock:.0f} g", stock_caption, THEME['SUCCESS'] if stock > 0 else _DIM)
        price = float(getattr(bean, 'price_per_kg', 0.0) or 0.0)
        if price > 0:
            # The stock's worth rides on its tile: a fifth tile would not fit the column.
            stock_tile.setToolTip(QApplication.translate("tilauscope_beancave", "Stock value: {0}").format(
                format_money(stock / 1000.0 * price)))
        tiles = [stock_tile]
        crop = int(getattr(bean, 'crop', 0) or 0)
        crop_col = THEME['TEXT']
        crop_tip = ""
        if crop > 0:
            age = datetime.now().astimezone().year - crop
            if age >= 3:
                crop_col = THEME['CRITICAL']
            elif age == 2:
                crop_col = THEME['WARNING']
            if age >= 2:
                crop_tip = QApplication.translate("tilauscope_beancave", "Harvest is {0} years old").format(age)
        crop_tile = self._tile(str(crop) if crop > 0 else "—",
                               QApplication.translate("tilauscope_common", "Crop"), crop_col)
        if crop_tip:
            crop_tile.setToolTip(crop_tip)
        tiles.append(crop_tile)
        sca = float(getattr(bean, 'sca', 0.0) or 0.0)
        tiles.append(self._tile(f"{sca:.1f}" if sca > 0 else "—",
                                QApplication.translate("tilauscope_common", "SCA"), THEME['TEXT']))
        tiles.append(self._tile(str(getattr(bean, 'count', 0) or 0),
                                QApplication.translate("tilauscope_beancave", "Roasts"), THEME['TEXT']))
        z.body.addLayout(self._tiles_row(tiles))

        # Flavour notes and the memo, edited together (SCA, notes, memo).
        flow_host = QWidget()
        flow_host.setStyleSheet(_PLAIN)
        flow = FlowLayout(flow_host, margin=0, spacing=_px(6))
        notes = [p.strip() for p in (bean.flavour_notes or "").split(',') if p.strip()][:8]
        for part in notes:
            flow.addWidget(_chip(part))
        if not notes:
            flow.addWidget(_label(QApplication.translate("tilauscope_beancave", "No flavour notes yet"),
                                  f"color:{_DIM};font-size:{_fs(12)}px;font-style:italic;"))
        edit_notes = QPushButton("✎")
        edit_notes.setCursor(Qt.CursorShape.PointingHandCursor)
        edit_notes.setStyleSheet(_link_css())
        edit_notes.setToolTip(QApplication.translate("tilauscope_common", "Edit SCA score, flavour notes and memo"))
        edit_notes.clicked.connect(lambda: self.editRequested.emit('sensory'))
        flow.addWidget(edit_notes)
        z.body.addWidget(flow_host)
        tips = (getattr(bean, 'tips', '') or "").strip()
        if tips:
            first = tips.splitlines()[0]
            short = first if len(first) <= 90 and first == tips else first[:88].rstrip() + "…"
            memo = _label(short, f"color:{THEME['SUBTEXT']};font-size:{_fs(11)}px;")
            memo.setToolTip(tips)
            z.body.addWidget(memo)
        self._add(self._left, z)

    def _build_memory(self, memory: RoastMemory | None, mode: str) -> None:
        z = _Zone(QApplication.translate("tilauscope_beancave", "Roast memory"), accent=True)
        z.edit_btn.hide()
        if memory is None:
            z.body.addWidget(_label(QApplication.translate("tilauscope_beancave", "Not roasted yet"),
                                    f"color:{THEME['TEXT']};font-size:{_fs(14)}px;font-weight:600;"))
            z.body.addWidget(_label(QApplication.translate(
                "tilauscope_beancave",
                "The first plan starts from this coffee's characteristics. Taste the result: "
                "what you note here steers the next roast."),
                f"color:{THEME['SUBTEXT']};font-size:{_fs(12)}px;", wrap=True))
            self._add(self._left, z)
            return

        all_btn = QPushButton(QApplication.translate("tilauscope_beancave", "All {0} roasts →").format(memory.count)
                              if memory.count > 1 else
                              QApplication.translate("tilauscope_beancave", "Open the roast →"))
        all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        all_btn.setStyleSheet(_link_css())
        all_btn.clicked.connect(self.allRoastsRequested.emit)
        z.head.addWidget(all_btn)

        tasting = memory.tasting
        line = [short_date(memory.epoch)] if memory.epoch > 0 else []
        if memory.level:
            line.append(memory.level)
        if memory.weight_in_g > 0:
            line.append(f"{memory.weight_in_g:.0f} g")
        z.body.addWidget(_label(" · ".join(line), f"color:{THEME['TEXT']};font-size:{_fs(14)}px;font-weight:600;"))

        facts_host = QWidget()
        facts_host.setStyleSheet(_PLAIN)
        facts = FlowLayout(facts_host, margin=0, spacing=_px(6))
        facts.setSpacing(_px(5))
        fact_css = (f"color:{THEME['TEXT']};font-size:{_fs(11)}px;background:{THEME['BORDER']};"
                    f"border:none;border-radius:6px;padding:{_px(1)}px {_px(7)}px;")
        basis = (QApplication.translate("tilauscope_beancave", "ground") if memory.colour_basis == 'ground'
                 else QApplication.translate("tilauscope_beancave", "whole"))
        for text, value, suffix in (
                (QApplication.translate("Label", "Development"),
                 f"{memory.dev_pct:.0f} %" if memory.dev_pct is not None else None, ""),
                (QApplication.translate("HTML Report Template", "Loss"),
                 f"{memory.loss_pct:.1f} %" if memory.loss_pct is not None else None, ""),
                (QApplication.translate("tilauscope_common", "Colour"),
                 f"{memory.colour:.0f}" if memory.colour is not None else None, " " + basis)):
            if value is None:
                continue
            f = QLabel(f"{text} <b style=\"font-family:{_MONO};\">{value}</b>{suffix}")
            f.setStyleSheet(fact_css)
            facts.addWidget(f)
        if facts.count():
            z.body.addWidget(facts_host)

        if tasting is not None:
            from tilauscope.cave.tasting_dialog import (  # noqa: PLC0415
                change_text, defect_labels, verdict_labels)
            labels = defect_labels()
            defects = [labels[d] for d in tasting.defects if d in labels]
            said = ", ".join(defects) if defects else verdict_labels().get(tasting.verdict, "")
            when = QApplication.translate("tilauscope_beancave", "Tasted:")
            try:
                when = QApplication.translate("tilauscope_beancave", "Tasted {0}:").format(
                    short_date(int(datetime.fromisoformat(tasting.iso_date).timestamp())))
            except (TypeError, ValueError):
                pass
            colour = THEME['CRITICAL'] if defects else THEME['SUCCESS']
            row = QHBoxLayout()
            row.setSpacing(_px(8))
            row.addWidget(_icon(_SVG_CUP, colour, 16))
            row.addWidget(_label(f"<span style=\"color:{THEME['SUBTEXT']};\">{when}</span> <b>{said}</b>",
                                 f"color:{colour};font-size:{_fs(13)}px;", wrap=True), 1)
            z.body.addLayout(row)
            if memory.change is not None:
                box = QFrame()
                box.setObjectName("nextTime")
                box.setStyleSheet(
                    f"QFrame#nextTime {{ background:{tint('WARNING', 0.08)};"
                    f"border:1px solid {tint('WARNING', 0.35)};border-radius:8px; }}")
                bl = QHBoxLayout(box)
                bl.setContentsMargins(_px(10), _px(7), _px(10), _px(7))
                bl.setSpacing(_px(8))
                bl.addWidget(_icon(_SVG_BULB, THEME['WARNING'], 17), 0, Qt.AlignmentFlag.AlignTop)
                bl.addWidget(_label(
                    f"<b style=\"color:{THEME['WARNING']};\">"
                    + QApplication.translate("tilauscope_beancave", "Next time:") + "</b> "
                    + change_text(memory.change[0], mode)[0],
                    f"color:{THEME['TEXT']};font-size:{_fs(12)}px;", wrap=True), 1)
                z.body.addWidget(box)
        elif ready_to_taste(memory):
            box = QFrame()
            box.setObjectName("tasteNow")
            box.setStyleSheet(
                f"QFrame#tasteNow {{ background:{tint('MAUVE', 0.10)};"
                f"border:1px solid {tint('MAUVE', 0.45)};border-radius:8px; }}")
            bl = QHBoxLayout(box)
            bl.setContentsMargins(_px(10), _px(6), _px(8), _px(6))
            bl.addWidget(_label(QApplication.translate(
                "tilauscope_beancave", "Rested {0} days — how did it taste?").format(memory.rest_days),
                f"color:{THEME['TEXT']};font-size:{_fs(12)}px;", wrap=True), 1)
            taste = QPushButton(QApplication.translate("tilauscope_beancave", "Taste…"))
            taste.setCursor(Qt.CursorShape.PointingHandCursor)
            taste.setStyleSheet(
                f"QPushButton {{ background:{THEME['MAUVE']};color:{THEME['BG']};border:none;"
                f"border-radius:7px;padding:5px 12px;font-weight:700;font-size:{_fs(12)}px; }}")
            uuid = memory.roast_uuid
            taste.clicked.connect(lambda: self.tasteRequested.emit(uuid))
            bl.addWidget(taste)
            z.body.addWidget(box)
        self._add(self._left, z)

    def _build_characteristics(self, bean) -> None:
        z = _Zone(QApplication.translate("CheckBox", "Characteristics"))
        z.edit_btn.setToolTip(QApplication.translate(
            "tilauscope_common", "Edit type, category, process, species, varieties, density, humidity"))
        z.edit_btn.clicked.connect(lambda: self.editRequested.emit('characteristics'))

        chips_host = QWidget()
        chips_host.setStyleSheet(_PLAIN)
        chips = FlowLayout(chips_host, margin=0, spacing=_px(6))
        lead = bean.process or bean.category
        if lead:
            chips.addWidget(_chip(lead, filled=THEME['MAUVE']))
        for word in (bean.species, None if getattr(bean, 'is_blend', False) else bean.varieties,
                     screen_size_label(getattr(bean, 'screen_size', '') or '')):
            if word:
                chips.addWidget(_chip(word))
        if chips.count():
            z.body.addWidget(chips_host)

        tiles = []
        for kind, value, text, caption in (
                ('density', float(getattr(bean, 'density', 0.0) or 0.0), "{0:.0f} g/l",
                 QApplication.translate("Label", "Density")),
                ('humidity', float(getattr(bean, 'last_humidity', 0.0) or 0.0), "{0:.1f} %",
                 QApplication.translate("Label", "Humidity")),
                ('aw', float(getattr(bean, 'water_activity', 0.0) or 0.0), "{0:.2f}",
                 QApplication.translate("tilauscope_beancave", "aw"))):
            if value <= 0:
                tile = self._tile("—", caption, _DIM)
                tile.setToolTip(QApplication.translate("tilauscope_beancave", "Not measured"))
                tiles.append(tile)
                continue
            word, colour = physical_qualifier(kind, value)
            tiles.append(self._tile(text.format(value), f"{caption} · {word}" if word else caption,
                                    colour or THEME['TEXT'], border=colour))
        z.body.addLayout(self._tiles_row(tiles))

        if getattr(bean, 'is_blend', False):
            z.body.addLayout(self._blend_bar(bean))

        family = match_variety_family(bean.varieties)
        if family is None:
            pace = QApplication.translate("tilauscope_beancave", "not known — standard pace")
        else:
            name, delta = family
            if delta > 0:
                word = QApplication.translate("tilauscope_common", "wants a faster roast")
            elif delta < 0:
                word = QApplication.translate("tilauscope_common", "takes a slower roast")
            else:
                word = QApplication.translate("tilauscope_common", "keeps the standard pace")
            pace = f"{name} — {word}"
        fam = QFrame()
        fam.setObjectName("familyLine")
        fam.setStyleSheet(f"QFrame#familyLine {{ background:{THEME['BORDER']};border:none;border-radius:8px; }}")
        fl = QHBoxLayout(fam)
        fl.setContentsMargins(_px(10), _px(6), _px(10), _px(6))
        fl.setSpacing(_px(8))
        fl.addWidget(_icon(_SVG_LEAF, THEME['SUBTEXT']))
        fl.addWidget(_label(QApplication.translate("tilauscope_beancave", "Bean family"),
                            f"color:{THEME['SUBTEXT']};font-size:{_fs(12)}px;"))
        fl.addWidget(_label(pace, f"color:{THEME['TEXT']};font-size:{_fs(12)}px;", wrap=True), 1)
        z.body.addWidget(fam)
        self._add(self._right, z)

    def _blend_bar(self, bean) -> QVBoxLayout:
        """Components as one segmented bar, the record itself first; ratio 0 = unknown."""
        comps: list[tuple[str, float]] = [
            (bean.varieties or bean.name or "?", float(getattr(bean, 'bean1_ratio', 0.0) or 0.0))]
        for n, r in ((getattr(bean, 'bean2_name', ''), float(getattr(bean, 'bean2_ratio', 0.0) or 0.0)),
                     (getattr(bean, 'bean3_name', ''), float(getattr(bean, 'bean3_ratio', 0.0) or 0.0))):
            if n or r > 0:
                comps.append((n or "?", r))
        lay = QVBoxLayout()
        lay.setSpacing(_px(5))
        bar = QHBoxLayout()
        bar.setSpacing(0)
        known = sum(r for _, r in comps if r > 0)
        for i, (_, r) in enumerate(comps):
            if r <= 0:
                continue
            seg = QFrame()
            seg.setFixedHeight(8)
            seg.setStyleSheet(f"background:{_BLEND_COLOURS[i % len(_BLEND_COLOURS)]};border:none;")
            bar.addWidget(seg, max(1, round(r)))
        if known < 100:
            rest = QFrame()
            rest.setFixedHeight(8)
            rest.setStyleSheet(f"background:{THEME['BORDER']};border:none;")
            bar.addWidget(rest, max(1, round(100 - known)))
        lay.addLayout(bar)
        legend_host = QWidget()
        legend_host.setStyleSheet(_PLAIN)
        legend = FlowLayout(legend_host, margin=0, spacing=_px(12))
        for i, (n, r) in enumerate(comps):
            colour = _BLEND_COLOURS[i % len(_BLEND_COLOURS)]
            legend.addWidget(_label(f"<span style=\"color:{colour};\">■</span> "
                                    + (f"{n} · {r:.0f} %" if r > 0 else n),
                                    f"color:{THEME['SUBTEXT']};font-size:{_fs(11)}px;"))
        lay.addWidget(legend_host)
        return lay

    def _build_provenance(self, bean) -> None:
        z = _Zone(QApplication.translate("tilauscope_common", "Provenance"))
        z.edit_btn.setToolTip(QApplication.translate("tilauscope_beancave", "Edit farm, supplier, altitude and price"))
        z.edit_btn.clicked.connect(lambda: self.editRequested.emit('provenance'))
        host = QWidget()
        host.setStyleSheet(_PLAIN)
        flow = FlowLayout(host, margin=0, spacing=_px(16))
        alt = int(getattr(bean, 'altitude', 0) or 0)
        price = float(getattr(bean, 'price_per_kg', 0.0) or 0.0)
        items = [
            (_SVG_PLACE, bean.farm or "", QApplication.translate("tilauscope_common", "Farm")),
            (_SVG_ALTITUDE, f"<b style=\"font-family:{_MONO};\">{alt}</b> m" if alt > 0 else "",
             QApplication.translate("tilauscope_common", "Altitude")),
            (_SVG_SUPPLIER, bean.supplier or "", QApplication.translate("tilauscope_common", "Supplier")),
            (_SVG_PRICE, f"{format_money(price)}/kg" if price > 0 else "",
             QApplication.translate("tilauscope_beancave", "Price")),
        ]
        for svg, text, name in items:
            if not text:
                continue
            item = QWidget()
            item.setStyleSheet(_PLAIN)
            item.setToolTip(name)
            il = QHBoxLayout(item)
            il.setContentsMargins(0, 0, 0, 0)
            il.setSpacing(_px(6))
            il.addWidget(_icon(svg, THEME['SUBTEXT']))
            il.addWidget(_label(text, f"color:{THEME['TEXT']};font-size:{_fs(12)}px;"))
            flow.addWidget(item)
        if not flow.count():
            flow.addWidget(_label(QApplication.translate("tilauscope_beancave", "Farm, altitude and supplier not entered"),
                                  f"color:{_DIM};font-size:{_fs(12)}px;font-style:italic;"))
        z.body.addWidget(host)
        self._add(self._right, z)

    def _build_sacks(self, bean) -> None:
        """One line: the bag labels when there are any, and the next harvest."""
        z = QFrame()
        z.setObjectName("sacksLine")
        z.setStyleSheet(
            f"QFrame#sacksLine {{ background:{THEME['SURFACE']};"
            f"border:1px solid {THEME['BORDER']};border-radius:10px; }}")
        row = QHBoxLayout(z)
        row.setContentsMargins(_px(14), _px(7), _px(10), _px(7))
        row.setSpacing(_px(10))
        sacks = list(getattr(bean, 'sacks', None) or [])
        # doctrine: no sacks → no label, no reminder
        if sacks:
            row.addWidget(_label(QApplication.translate("tilauscope_common", "Sacks").upper(),
                                 f"color:{_DIM};font-size:{_fs(10)}px;letter-spacing:2px;"))
            chips = SackChipsRow()
            chips.set_sacks(sacks)
            chips.sackReleased.connect(self.sackReleased.emit)
            chips.setToolTip(QApplication.translate("tilauscope_beancave", "✕ releases the label (reusable)"))
            chips.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
            row.addWidget(chips)
        row.addStretch(1)
        crop = QPushButton("🌱 " + QApplication.translate("tilauscope_common", "New crop"))
        crop.setCursor(Qt.CursorShape.PointingHandCursor)
        crop.setStyleSheet(
            f"QPushButton {{ background:transparent;color:{THEME['ACCENT']};"
            f"border:1px solid {THEME['BORDER']};border-radius:6px;padding:4px 10px;font-weight:600;"
            f"font-size:{_fs(12)}px; }}"
            f"QPushButton:hover {{ border-color:{THEME['ACCENT']}; }}")
        crop.setToolTip(QApplication.translate(
            "tilauscope_beancave",
            "Start the next harvest of the selected coffee: origin, process "
            "and variety are inherited, you only enter the new year, the "
            "weight and the measurements of the lot."))
        crop.clicked.connect(self.newCropRequested.emit)
        row.addWidget(crop)
        self._add(self._right, z)

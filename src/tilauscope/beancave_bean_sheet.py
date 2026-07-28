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

## TILAU ##
"""Read-first bean sheet for BeanCave (Lot 5, step B — validated mock).

Replaces the permanent editing form of the Green Beans tab with a
presentation view structured in zones, mirroring the wizard's review page:

    ESSENTIALS  — hero: name + BLEND badge, origin · process · supplier,
                  stat tiles (Stock / Crop / SCA / Roasts)
    PROVENANCE  — farm, supplier, altitude
    CHARACTERISTICS — species, varieties, category, blend composition,
                  density, humidity, water activity
    SENSORY     — flavour notes as chips + roasting tips
    SACKS       — attached sack labels (chips with ✕ release);
                  the zone is absent when the bean has no sacks

Each zone carries a ✎ Edit button that emits ``editRequested(zone_key)`` —
the host decides what editing means (step B: switch to the legacy form;
step C: targeted zone editors). The sheet itself never writes anything.
"""

from __future__ import annotations

import logging
from datetime import datetime

from PyQt6.QtCore import Qt, pyqtSignal
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

from tilauscope.sack_manager import SackChipsRow
from tilauscope.tilauscope_types import THEME

_logd = logging.getLogger('tilaudebug')

_MONO = "'JetBrains Mono', monospace"
_DIM = "#6C7086"



class _Zone(QFrame):
    """Titled surface card with an optional ✎ Edit button."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            f"_Zone {{ background:{THEME['SURFACE']};"
            f"border:1px solid {THEME['BORDER']};border-radius:10px; }}")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(14, 10, 14, 12)
        self.body.setSpacing(8)

        head = QHBoxLayout()
        t = QLabel(title.upper())
        t.setStyleSheet(
            f"color:{_DIM};font-family:{_MONO};font-size:10px;"
            f"letter-spacing:2px;background:transparent;border:none;")
        head.addWidget(t, 1)
        self.edit_btn = QPushButton("✎ " + QApplication.translate("tilauscope_beancave", "Edit"))
        self.edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.edit_btn.setStyleSheet(
            f"QPushButton {{ color:{THEME['ACCENT']};background:transparent;"
            f"border:1px solid transparent;border-radius:7px;"
            f"padding:2px 9px;font-size:11px; }}"
            f"QPushButton:hover {{ border:1px solid {THEME['ACCENT']};"
            f"background:rgba(137,180,250,0.08); }}")
        head.addWidget(self.edit_btn)
        self.body.addLayout(head)


class BeanSheetWidget(QWidget):
    """Scrollable read-only sheet; rebuilt on ``set_bean``."""

    editRequested = pyqtSignal(str)   # noqa: N815 — 'essentials'|'provenance'|'characteristics'|'sensory'
    sackReleased = pyqtSignal(str)    # noqa: N815 — re-emitted from the chips row

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(f"QScrollArea {{ background:{THEME['BG']};border:none; }}")
        self._host = QWidget()
        self._host.setStyleSheet(f"background:{THEME['BG']};")
        self._lay = QVBoxLayout(self._host)
        self._lay.setContentsMargins(14, 12, 14, 14)
        self._lay.setSpacing(11)
        self._lay.addStretch(1)
        scroll.setWidget(self._host)
        root.addWidget(scroll)
        self._zones: list[QWidget] = []

    # ── public API ───────────────────────────────────────────────────────────
    def clear(self) -> None:
        for z in self._zones:
            self._lay.removeWidget(z)
            z.deleteLater()
        self._zones = []

    def set_bean(self, bean) -> None:
        self.clear()
        try:
            self._build_hero(bean)
            self._build_provenance(bean)
            self._build_characteristics(bean)
            self._build_sensory(bean)
            self._build_sacks(bean)
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _logd.exception("bean sheet render failed")

    # ── zones ────────────────────────────────────────────────────────────────
    def _add(self, zone: QWidget) -> None:
        self._lay.insertWidget(len(self._zones), zone)
        self._zones.append(zone)

    def _build_hero(self, bean) -> None:
        z = _Zone(QApplication.translate("tilauscope_beancave", "Essentials"))
        z.edit_btn.setToolTip(QApplication.translate("tilauscope_beancave", "Edit name, origin, year and stock"))
        z.edit_btn.clicked.connect(lambda: self.editRequested.emit('essentials'))

        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        name = QLabel(bean.name or "—")
        name.setWordWrap(True)
        name.setStyleSheet(
            f"color:{THEME['TEXT']};font-size:18px;font-weight:700;"
            f"background:transparent;border:none;")
        name_row.addWidget(name, 1)
        if getattr(bean, 'is_blend', False):
            b = QLabel("BLEND")
            b.setStyleSheet(
                f"color:{THEME['ACCENT']};font-family:{_MONO};font-size:9px;"
                f"font-weight:600;border:1px solid {THEME['ACCENT']};"
                f"border-radius:8px;padding:1px 6px;background:transparent;")
            name_row.addWidget(b, 0, Qt.AlignmentFlag.AlignTop)
        z.body.addLayout(name_row)

        sub_parts = [p for p in (bean.country, bean.process, bean.supplier) if p]
        sub = QLabel(" · ".join(sub_parts) if sub_parts else "—")
        sub.setStyleSheet(f"color:{THEME['SUBTEXT']};font-size:12px;background:transparent;border:none;")
        sub.setWordWrap(True)
        z.body.addWidget(sub)

        tiles = QHBoxLayout()
        tiles.setSpacing(9)
        stock = getattr(bean, 'weight_left', 0.0) or 0.0
        tiles.addWidget(self._tile(
            f"{stock:.0f} g", QApplication.translate("tilauscope_beancave", "Stock"),
            THEME['SUCCESS'] if stock > 0 else _DIM))
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
        crop_tile = self._tile(str(crop) if crop > 0 else "—", QApplication.translate("tilauscope_beancave", "Crop"), crop_col)
        if crop_tip:
            crop_tile.setToolTip(crop_tip)
        tiles.addWidget(crop_tile)
        sca = getattr(bean, 'sca', 0.0) or 0.0
        tiles.addWidget(self._tile(f"{sca:.1f}" if sca > 0 else "—", QApplication.translate("tilauscope_beancave", "SCA"), THEME['TEXT']))
        tiles.addWidget(self._tile(str(getattr(bean, 'count', 0) or 0), QApplication.translate("tilauscope_beancave", "Roasts"), THEME['TEXT']))
        tiles.addStretch(1)
        z.body.addLayout(tiles)
        self._add(z)

    def _tile(self, value: str, caption: str, color: str) -> QFrame:
        t = QFrame()
        t.setStyleSheet(
            f"QFrame {{ background:{THEME['BG']};border:1px solid {THEME['BORDER']};"
            f"border-radius:9px; }}")
        tl = QVBoxLayout(t)
        tl.setContentsMargins(12, 6, 12, 6)
        tl.setSpacing(0)
        v = QLabel(value)
        v.setStyleSheet(
            f"color:{color};font-family:{_MONO};font-size:14px;"
            f"font-weight:600;background:transparent;border:none;")
        c = QLabel(caption.upper())
        c.setStyleSheet(
            f"color:{_DIM};font-size:9px;letter-spacing:1px;"
            f"background:transparent;border:none;")
        tl.addWidget(v)
        tl.addWidget(c)
        return t

    def _kv_grid(self, zone: _Zone, pairs: list[tuple[str, str]]) -> None:
        g = QGridLayout()
        g.setHorizontalSpacing(18)
        g.setVerticalSpacing(3)
        g.setColumnStretch(1, 1)
        for r, (k, v) in enumerate(pairs):
            kl = QLabel(k)
            kl.setStyleSheet(f"color:{_DIM};font-size:12px;background:transparent;border:none;")
            missing = not v or v == "—"
            vl = QLabel(v if not missing else "—")
            vl.setWordWrap(True)
            vl.setStyleSheet(
                f"color:{_DIM if missing else THEME['TEXT']};font-size:12px;"
                f"{'font-style:italic;' if missing else ''}"
                f"background:transparent;border:none;")
            g.addWidget(kl, r, 0, Qt.AlignmentFlag.AlignTop)
            g.addWidget(vl, r, 1)
        zone.body.addLayout(g)

    def _build_provenance(self, bean) -> None:
        z = _Zone(QApplication.translate("tilauscope_beancave", "Provenance"))
        z.edit_btn.setToolTip(QApplication.translate("tilauscope_beancave", "Edit farm, supplier and altitude"))
        z.edit_btn.clicked.connect(lambda: self.editRequested.emit('provenance'))
        alt = int(getattr(bean, 'altitude', 0) or 0)
        self._kv_grid(z, [
            (QApplication.translate("tilauscope_beancave", "Farm"), bean.farm or "—"),
            (QApplication.translate("tilauscope_beancave", "Supplier"), bean.supplier or "—"),
            (QApplication.translate("tilauscope_beancave", "Altitude"), f"{alt} m" if alt > 0 else "—"),
        ])
        self._add(z)

    def _build_characteristics(self, bean) -> None:
        z = _Zone(QApplication.translate("tilauscope_beancave", "Characteristics"))
        z.edit_btn.setToolTip(QApplication.translate("tilauscope_beancave", "Edit type, category, process, species, varieties, density, humidity"))
        z.edit_btn.clicked.connect(lambda: self.editRequested.emit('characteristics'))
        dens = getattr(bean, 'density', 0.0) or 0.0
        hum = getattr(bean, 'last_humidity', 0.0) or 0.0
        wa = getattr(bean, 'water_activity', 0.0) or 0.0
        pairs: list[tuple[str, str]] = [
            (QApplication.translate("tilauscope_beancave", "Species"), bean.species or "—"),
            (QApplication.translate("tilauscope_beancave", "Varieties"), bean.varieties or "—"),
            (QApplication.translate("tilauscope_beancave", "Category"), bean.category or "—"),
            (QApplication.translate("tilauscope_beancave", "Process"), bean.process or "—"),
        ]
        if getattr(bean, 'is_blend', False):
            # component 1 is the record itself — show its own variety first,
            # then each named component with its ratio (ratio 0 = unknown)
            comps: list[tuple[str, float]] = [
                (bean.varieties or bean.name or "?",
                 getattr(bean, 'bean1_ratio', 0.0) or 0.0)]
            for n, r in ((getattr(bean, 'bean2_name', ''), getattr(bean, 'bean2_ratio', 0.0) or 0.0),
                         (getattr(bean, 'bean3_name', ''), getattr(bean, 'bean3_ratio', 0.0) or 0.0)):
                if n or r > 0:
                    comps.append((n or "?", r))
            comp = " · ".join(
                f"{r:.0f} % {n}" if r > 0 else n for n, r in comps)
            pairs.append((QApplication.translate("tilauscope_beancave", "Composition"), comp))
        pairs += [
            (QApplication.translate("tilauscope_beancave", "Density"), f"{dens:.0f} g/l" if dens > 0 else "—"),
            (QApplication.translate("tilauscope_beancave", "Humidity"), f"{hum:.1f} %" if hum > 0 else "—"),
            (QApplication.translate("tilauscope_beancave", "Water activity"), f"{wa:.2f}" if wa > 0 else "—"),
        ]
        self._kv_grid(z, pairs)
        self._add(z)

    def _build_sensory(self, bean) -> None:
        z = _Zone(QApplication.translate("tilauscope_beancave", "Sensory & notes"))
        z.edit_btn.setToolTip(QApplication.translate("tilauscope_beancave", "Edit SCA score, flavour notes and memo"))
        z.edit_btn.clicked.connect(lambda: self.editRequested.emit('sensory'))
        notes = (bean.flavour_notes or "").strip()
        if notes:
            chips = QHBoxLayout()
            chips.setSpacing(6)
            wrap = QWidget()
            wrap.setStyleSheet("background:transparent;border:none;")
            wl = QHBoxLayout(wrap)
            wl.setContentsMargins(0, 0, 0, 0)
            wl.setSpacing(6)
            for part in [p.strip() for p in notes.split(',') if p.strip()][:8]:
                c = QLabel(part)
                c.setStyleSheet(
                    f"color:{THEME['TEXT']};font-size:11px;background:{THEME['BG']};"
                    f"border:1px solid {THEME['BORDER']};border-radius:9px;padding:2px 9px;")
                wl.addWidget(c)
            wl.addStretch(1)
            chips.addWidget(wrap)
            z.body.addLayout(chips)
        else:
            e = QLabel("—")
            e.setStyleSheet(f"color:{_DIM};font-size:12px;font-style:italic;background:transparent;border:none;")
            z.body.addWidget(e)
        tips = (getattr(bean, 'tips', '') or "").strip()
        if tips:
            tl = QLabel(tips)
            tl.setWordWrap(True)
            tl.setStyleSheet(
                f"color:{THEME['SUBTEXT']};font-size:11.5px;background:transparent;"
                f"border:none;border-top:1px dashed {THEME['BORDER']};padding-top:6px;")
            z.body.addWidget(tl)
        self._add(z)

    def _build_sacks(self, bean) -> None:
        sacks = list(getattr(bean, 'sacks', None) or [])
        # doctrine: no sacks → no zone, no reminder, nothing
        if not sacks:
            return
        z = _Zone(QApplication.translate("tilauscope_beancave", "Sacks"))
        z.edit_btn.hide()
        row = QHBoxLayout()
        row.setSpacing(10)
        chips = SackChipsRow()
        chips.set_sacks(sacks)
        chips.sackReleased.connect(self.sackReleased.emit)
        chips.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        row.addWidget(chips)
        hint = QLabel(QApplication.translate("tilauscope_beancave", "✕ releases the label (reusable)"))
        hint.setStyleSheet(f"color:{_DIM};font-size:10.5px;background:transparent;border:none;")
        row.addWidget(hint)
        row.addStretch(1)
        z.body.addLayout(row)
        self._add(z)

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

"""The head of the Roasts tab detail: a roast's figures, its result banner, the curve message.

The figures come from the loaded profile through plain functions, so what a tile
says is checked without building the dialog; the widgets only show it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                             QVBoxLayout)

# The summary of a roast (facts, tiles, level of a colour) lives in the library
# shared with the tablet.
from tilaucore import roast_summary as _summary
from tilaucore.roast_summary import DASH, RoastFacts, colour_category, mss, roast_facts  # noqa: F401
from tilauscope.theme_qss import tint
from tilauscope.tilauscope_types import THEME, format_money

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

@dataclass(frozen=True, slots=True)
class TileText:
    caption: str
    value: str = DASH
    sub: str = ''
    swatch: str = ''        # the colour of the dot beside the value, or none
    swatch_filled: bool = True   # a hollow ring instead of a filled dot
    tip: str = ''           # the tooltip of the sub line; the sub itself when empty


def _not_recorded(caption: str) -> TileText:
    return TileText(caption, DASH, QApplication.translate('tilauscope_beancave', 'Not recorded'))


def _degrees(value: float, unit: str) -> str:
    return f'{value:.0f} °{unit}'


def _spread(text: str) -> str:
    return QApplication.translate('tilauscope_beancave', 'Spread {0}').format(text)


def roast_tiles(facts: RoastFacts | None, price_per_kg: float = 0.0) -> list[TileText]:
    """Roasted weight, roast time, drop temperature and colour — each with what it means.

    The tiles are the library's, shared with the tablet; here they are translated,
    and the roast cost is shown in the operator's currency.
    """
    tiles = []
    for tile in _summary.roast_tiles(facts, price_per_kg):
        sub = ' · '.join(QApplication.translate(*text).format(*args) for text, args in tile.sub)
        tip = ''
        if tile.cost is not None:
            sub += f' · {format_money(tile.cost)}'
            tip = QApplication.translate('tilauscope_beancave', 'Roast cost {0} · {1} per roasted kg').format(
                format_money(tile.cost), format_money(tile.cost_per_roasted_kg))
        tiles.append(TileText(QApplication.translate(*tile.caption), tile.value, sub, tile.swatch,
                              tile.swatch_filled, tip))
    return tiles


def energy_tile(profile: Mapping | None) -> TileText:
    """Energy of the roast, CHARGE to DROP: kWh, then kWh/kg green and where it comes from.

    From the profile's own energy bill, else rebuilt from its saved power curve.
    """
    caption = QApplication.translate('Tab', 'Energy')
    if not profile:
        return TileText(caption)
    from tilauscope.energy_model import NONE, session_for_profile
    from tilauscope.energy_panel import fmt_kwh, provenance, summarize_profile
    session = session_for_profile(dict(profile))
    summary = summarize_profile(dict(profile), session) if session is not None else None
    if summary is None or summary.roast is None:
        return _not_recorded(caption)
    roast = summary.total(summary.roast.per_channel)
    if roast.provenance == NONE:
        return _not_recorded(caption)
    glyph, _colour, words = provenance(roast)
    bits = []
    if summary.wh_per_kg is not None:
        bits.append(QApplication.translate('tilauscope_beancave', '{0} kWh/kg').format(
            f'{summary.wh_per_kg / 1000:.3f}'))
    bits.append(f'{glyph} {words}')
    if session is not None and session.rebuilt:
        bits.append(QApplication.translate('tilauscope_beancave', 'rebuilt'))
    return TileText(caption, fmt_kwh(roast.wh), ' · '.join(bits))


def comparison_tiles(all_facts: Sequence[RoastFacts] | None) -> list[TileText]:
    """Roast time, drop temperature and colour across the compared roasts: a range and its spread."""
    captions = (QApplication.translate('tilauscope_beancave', 'Roast time'),
                QApplication.translate('tilauscope_beancave', 'Drop temperature'),
                QApplication.translate('tilauscope_common', 'Colour'))
    if all_facts is None:
        return [TileText(caption) for caption in captions]

    times = [facts.total_s for facts in all_facts if facts.total_s > 0]
    if len(times) >= 2:
        duration = TileText(captions[0], f'{mss(min(times))} – {mss(max(times))}',
                            _spread(mss(max(times) - min(times))))
    else:
        duration = _not_recorded(captions[0])

    drops = [facts for facts in all_facts if facts.drop_bt > 0]
    units = {facts.unit for facts in drops}
    if len(drops) >= 2 and len(units) == 1:
        unit = units.pop()
        low, high = min(f.drop_bt for f in drops), max(f.drop_bt for f in drops)
        drop = TileText(captions[1], f'{low:.0f} – {high:.0f} °{unit}', _spread(_degrees(high - low, unit)))
    else:
        drop = _not_recorded(captions[1])

    # One kind of reading across every roast, or no range at all: ground and
    # whole bean are different measurements and are never pooled.
    readings: list[float] = []
    kind = ''
    if len(all_facts) >= 2 and all(facts.ground > 0 for facts in all_facts):
        readings = [facts.ground for facts in all_facts]
        kind = QApplication.translate('tilauscope_beancave', 'Ground · {0}')
    elif len(all_facts) >= 2 and all(facts.whole > 0 for facts in all_facts):
        readings = [facts.whole for facts in all_facts]
        kind = QApplication.translate('tilauscope_beancave', 'Whole bean · {0}')
    if readings:
        low, high = min(readings), max(readings)
        colour = TileText(captions[2], f'{low:.0f} – {high:.0f}', kind.format(_spread(f'{high - low:.0f}')))
    else:
        colour = _not_recorded(captions[2])
    return [duration, drop, colour]


#: The shortest custom time range that still reads as a curve.
MIN_RANGE_S = 30


def custom_range_error(low: int, high: int) -> str:
    """Why a custom time range cannot be read, in seconds, or '' when it can.

    A refused range has to carry its reason: a control that goes back to what it
    was, on its own, leaves the operator nothing to act on.
    """
    if high - low < MIN_RANGE_S:
        return QApplication.translate(
            'tilauscope_beancave',
            'The end must be at least {0} seconds after the start.').format(MIN_RANGE_S)
    return ''


def menu_qss() -> str:
    """The Export and ⋯ menus: a popup is a window of its own, so it carries its sheet."""
    return (f"QMenu {{ background-color: {THEME['SURFACE']}; color: {THEME['TEXT']};"
            f" border: 1px solid {THEME['BORDER']}; padding: 4px; }}"
            f"QMenu::item {{ padding: 6px 18px; border-radius: 4px; }}"
            f"QMenu::item:selected {{ background-color: {THEME['BORDER']}; }}"
            f"QMenu::item:disabled {{ color: {THEME['OVERLAY0']}; }}"
            f"QMenu::separator {{ height: 1px; background: {THEME['BORDER']}; margin: 4px 8px; }}")


class KpiTile(QFrame):
    """One figure of a roast: what it is, its value, and what the value means.

    A clickable tile shows a chevron and emits `clicked`; the others never do.
    """

    clicked = pyqtSignal()

    def __init__(self, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._clickable = False
        self.setProperty('variant', 'card')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(2)
        self._caption = QLabel('')
        self._caption.setProperty('variant', 'caption')
        self._swatch = QLabel()
        self._swatch.setFixedSize(10, 10)
        self._swatch.hide()
        self._value = QLabel(DASH)
        self._value.setProperty('variant', 'readout-sm')
        value_row = QHBoxLayout()
        value_row.setSpacing(6)
        value_row.addWidget(self._swatch, 0, Qt.AlignmentFlag.AlignVCenter)
        value_row.addWidget(self._value)
        value_row.addStretch(1)
        self._chevron = QLabel('›')
        self._chevron.setStyleSheet(f"font-size: 16px; font-weight: 700; color: {THEME['ACCENT']};")
        self._chevron.hide()
        value_row.addWidget(self._chevron)
        self._sub = QLabel('')
        self._sub.setProperty('variant', 'caption')
        # One line high even when empty, so a figure arriving never moves the others.
        self._sub.setMinimumHeight(self._sub.fontMetrics().height())
        for label in (self._caption, self._sub):
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self._caption)
        layout.addLayout(value_row)
        layout.addWidget(self._sub)

    def set_clickable(self, on: bool, tip: str = '') -> None:
        self._clickable = on
        self._chevron.setVisible(on)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor if on else Qt.CursorShape.ArrowCursor))
        self.setToolTip(tip if on else '')

    def mouseReleaseEvent(self, event) -> None:  # noqa: ANN001, N802
        # A Qt virtual: an exception escaping it closes the application.
        try:
            inside = (self._clickable and event.button() == Qt.MouseButton.LeftButton
                      and self.rect().contains(event.position().toPoint()))
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            inside = False
        super().mouseReleaseEvent(event)
        if inside:
            self.clicked.emit()

    def show_text(self, text: TileText) -> None:
        self._caption.setText(text.caption)
        self._value.setText(text.value)
        self._sub.setText(text.sub)
        self._sub.setToolTip(text.tip or text.sub)
        if text.swatch:
            fill = text.swatch if text.swatch_filled else 'transparent'
            rim = THEME['OVERLAY0'] if text.swatch_filled else text.swatch
            self._swatch.setStyleSheet(f"background-color: {fill}; border-radius: 5px;"
                                       f" border: {1 if text.swatch_filled else 2}px solid {rim};")
            self._swatch.show()
        else:
            self._swatch.hide()


class ResultBanner(QFrame):
    """Above a roast whose result was never filled in: says so, and offers the form."""

    record_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self.setObjectName('roastResultBanner')
        self.setStyleSheet(f"""
            QFrame#roastResultBanner {{
                background-color: {tint('WARNING', 28)};
                border: 1px solid {tint('WARNING', 90)};
                border-radius: 8px;
            }}
            QFrame#roastResultBanner QLabel {{ background: transparent; }}
            QFrame#roastResultBanner QPushButton {{
                background-color: {tint('WARNING', 45)};
                color: {THEME['WARNING']};
                border: 1px solid {tint('WARNING', 120)};
                border-radius: 6px;
                padding: 4px 12px;
                font-weight: 600;
            }}
            QFrame#roastResultBanner QPushButton:hover {{ background-color: {tint('WARNING', 75)}; }}
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 8, 6)
        layout.setSpacing(8)
        glyph = QLabel('◌')
        glyph.setStyleSheet(f"color: {THEME['WARNING']}; font-size: 14px;")
        text = QLabel(QApplication.translate('tilauscope_beancave',
                                             'No result yet — weight and colour are missing'))
        text.setWordWrap(True)
        button = QPushButton(QApplication.translate('tilauscope_beancave', 'Record result'))
        button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        button.clicked.connect(self.record_requested)
        layout.addWidget(glyph)
        layout.addWidget(text, 1)
        layout.addWidget(button)
        self.hide()


class TastingBanner(QFrame):
    """Under a rested roast: asks how it tasted, or recalls what was said."""

    taste_requested = pyqtSignal()
    reference_toggled = pyqtSignal(bool)

    def __init__(self, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self.setObjectName('roastTastingBanner')
        self.setStyleSheet(f"""
            QFrame#roastTastingBanner {{
                border: 1px solid {tint('MAUVE', 110)};
                border-radius: 8px;
            }}
            QFrame#roastTastingBanner QLabel {{ background: transparent; border: none; }}
            QFrame#roastTastingBanner QPushButton {{
                background: transparent; color: {THEME['MAUVE']};
                border: none; padding: 4px 8px; font-weight: 600;
            }}
            QFrame#roastTastingBanner QPushButton#reference {{
                color: {THEME['OVERLAY1']}; border: 1px solid {THEME['SURFACE1']};
                border-radius: 6px; padding: 0; font-size: 16px; font-weight: 400;
            }}
            QFrame#roastTastingBanner QPushButton#reference:checked {{
                color: {THEME['YELLOW']}; border-color: {THEME['YELLOW']};
                background: {tint('YELLOW', 28)};
            }}
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 8, 6)
        layout.setSpacing(8)
        glyph = QLabel('☕')
        self._text = QLabel()
        self._text.setWordWrap(True)
        self._button = QPushButton()
        self._button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._button.clicked.connect(self.taste_requested)
        self._reference = QPushButton()
        self._reference.setObjectName('reference')
        self._reference.setCheckable(True)
        self._reference.setFixedSize(30, 26)
        self._reference.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._reference.clicked.connect(self.reference_toggled)
        self._reference.hide()
        layout.addWidget(glyph)
        layout.addWidget(self._text, 1)
        layout.addWidget(self._button)
        layout.addWidget(self._reference)
        self.hide()

    def show_state(self, text: str, button: str) -> None:
        self._text.setText(text)
        self._button.setText(button + " ›")
        self.show()

    def set_reference(self, offered: bool, on: bool) -> None:
        """The reference star: offered on a roast tasted Yes or on the reference, filled on the reference."""
        self._reference.blockSignals(True)
        self._reference.setChecked(on)
        self._reference.blockSignals(False)
        self._reference.setText('★' if on else '☆')
        self._reference.setToolTip(
            QApplication.translate('tilauscope_beancave', 'Reference roast — click to remove') if on else
            QApplication.translate('tilauscope_beancave', 'Make it the reference roast'))
        self._reference.setVisible(offered)


class CurveMessageLabel(QLabel):
    """The line above the curve: shown while it carries a message, gone when it is empty."""

    def setText(self, text: str | None) -> None:  # noqa: N802
        super().setText(text or '')
        self.setVisible(bool(text))

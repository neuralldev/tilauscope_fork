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

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                             QVBoxLayout)

from tilauscope.alogmanager import _to_grams
from tilauscope.theme_qss import tint
from tilauscope.tilauscope_types import AGTRON_SCALES, THEME, get_agtron_color

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

DASH = '—'


def mss(seconds: float) -> str:
    """m:ss, the way roast times are read."""
    total = int(round(seconds))
    return f'{total // 60}:{total % 60:02d}'


def _number(value: object) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if math.isnan(number) or math.isinf(number) else number


@dataclass(frozen=True, slots=True)
class RoastFacts:
    """What the tiles show about one roast, read from its profile."""
    weight_in_g: float
    weight_out_g: float
    total_s: float          # CHARGE to DROP; 0 when either is unmarked
    development_s: float    # first crack to DROP; 0 when first crack is unmarked
    drop_bt: float
    first_crack_bt: float
    unit: str               # the profile's own, 'C' or 'F'
    ground: float
    whole: float

    @property
    def has_result(self) -> bool:
        """A roasted weight or a colour — what the result form records."""
        return self.weight_out_g > 0 or self.ground > 0 or self.whole > 0


def roast_facts(profile: Mapping) -> RoastFacts:
    computed = profile.get('computed')
    if not isinstance(computed, dict):
        computed = {}
    drop_s = _number(computed.get('DROP_time')) or _number(computed.get('totaltime'))
    first_crack_s = _number(computed.get('FCs_time'))
    weight = profile.get('weight')
    return RoastFacts(
        weight_in_g=_to_grams(weight, 0),
        weight_out_g=_to_grams(weight, 1),
        total_s=drop_s,
        development_s=drop_s - first_crack_s if 0 < first_crack_s < drop_s else 0.0,
        drop_bt=_number(computed.get('DROP_BT')),
        first_crack_bt=_number(computed.get('FCs_BT')),
        unit='F' if str(profile.get('mode') or 'C').upper() == 'F' else 'C',
        ground=_number(profile.get('ground_color')),
        whole=_number(profile.get('whole_color')),
    )


def ground_category(value: float) -> str:
    """The Agtron category of a ground reading — ground only: the names belong to that scale."""
    for scale in AGTRON_SCALES:
        if scale.agtron_range.min_value <= value <= scale.agtron_range.max_value:
            return scale.name
    return ''


@dataclass(frozen=True, slots=True)
class TileText:
    caption: str
    value: str = DASH
    sub: str = ''
    swatch: str = ''        # the colour of the dot beside the value, or none
    swatch_filled: bool = True   # a hollow ring instead of a filled dot


def _not_recorded(caption: str) -> TileText:
    return TileText(caption, DASH, QApplication.translate('tilauscope_beancave', 'Not recorded'))


def _degrees(value: float, unit: str) -> str:
    return f'{value:.0f} °{unit}'


def _spread(text: str) -> str:
    return QApplication.translate('tilauscope_beancave', 'Spread {0}').format(text)


def roast_tiles(facts: RoastFacts | None) -> list[TileText]:
    """Roasted weight, roast time, drop temperature and colour — each with what it means.

    Without facts (the roast is still loading, or could not be read) every tile
    keeps its caption and shows a dash, so nothing moves when the figures land.
    """
    captions = (QApplication.translate('tilauscope_beancave', 'Roasted weight'),
                QApplication.translate('tilauscope_beancave', 'Roast time'),
                QApplication.translate('tilauscope_beancave', 'Drop temperature'),
                QApplication.translate('tilauscope_beancave', 'Colour'))
    if facts is None:
        return [TileText(caption) for caption in captions]

    if facts.weight_out_g > 0:
        sub = ''
        if facts.weight_in_g > 0:
            loss = max(0.0, (facts.weight_in_g - facts.weight_out_g) / facts.weight_in_g * 100.0)
            sub = QApplication.translate('tilauscope_beancave', '−{0} % from {1} g').format(
                f'{loss:.0f}', f'{facts.weight_in_g:.0f}')
        weight = TileText(captions[0], f'{facts.weight_out_g:.0f} g', sub)
    else:
        weight = _not_recorded(captions[0])

    if facts.total_s > 0:
        sub = (QApplication.translate('tilauscope_beancave', 'Development {0}').format(mss(facts.development_s))
               if facts.development_s > 0 else '')
        duration = TileText(captions[1], mss(facts.total_s), sub)
    else:
        duration = _not_recorded(captions[1])

    if facts.drop_bt > 0:
        sub = (QApplication.translate('tilauscope_beancave', 'First crack at {0}').format(
                   _degrees(facts.first_crack_bt, facts.unit)) if facts.first_crack_bt > 0 else '')
        drop = TileText(captions[2], _degrees(facts.drop_bt, facts.unit), sub)
    else:
        drop = _not_recorded(captions[2])

    if facts.ground > 0:
        category = ground_category(facts.ground)
        sub = (QApplication.translate('tilauscope_beancave', 'Ground · {0}').format(category) if category
               else QApplication.translate('tilauscope_beancave', 'Ground'))
        colour = TileText(captions[3], f'{facts.ground:.0f}', sub, get_agtron_color(facts.ground))
    elif facts.whole > 0:
        # The dot shows the reading on the same roast scale as everywhere else,
        # hollow because a whole bean reads a shade darker than its ground
        # equivalent. The category name stays out: naming a roast level is a
        # claim, and the names belong to ground readings.
        colour = TileText(captions[3], f'{facts.whole:.0f}',
                          QApplication.translate('tilauscope_beancave', 'Whole bean'),
                          get_agtron_color(facts.whole), swatch_filled=False)
    else:
        colour = _not_recorded(captions[3])
    return [weight, duration, drop, colour]


def comparison_tiles(all_facts: Sequence[RoastFacts] | None) -> list[TileText]:
    """Roast time, drop temperature and colour across the compared roasts: a range and its spread."""
    captions = (QApplication.translate('tilauscope_beancave', 'Roast time'),
                QApplication.translate('tilauscope_beancave', 'Drop temperature'),
                QApplication.translate('tilauscope_beancave', 'Colour'))
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
    """One figure of a roast: what it is, its value, and what the value means."""

    def __init__(self, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
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
        self._sub = QLabel('')
        self._sub.setProperty('variant', 'caption')
        # One line high even when empty, so a figure arriving never moves the others.
        self._sub.setMinimumHeight(self._sub.fontMetrics().height())
        for label in (self._caption, self._sub):
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self._caption)
        layout.addLayout(value_row)
        layout.addWidget(self._sub)

    def show_text(self, text: TileText) -> None:
        self._caption.setText(text.caption)
        self._value.setText(text.value)
        self._sub.setText(text.sub)
        self._sub.setToolTip(text.sub)
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


class CurveMessageLabel(QLabel):
    """The line above the curve: shown while it carries a message, gone when it is empty."""

    def setText(self, text: str | None) -> None:  # noqa: N802
        super().setText(text or '')
        self.setVisible(bool(text))

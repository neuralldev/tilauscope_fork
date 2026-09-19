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

"""The Roasts tab list: one roast per two-line row, grouped by day or by coffee.

The model holds the rows the folder scan built, the proxy filters and orders
them, and the delegate paints a row with the heading of its group above the
first one. Headings are painted, never rows: the selection, the keyboard and a
Shift-click only ever reach roasts, and a roast the search hides cannot be
selected through a range that spans it.
"""

from __future__ import annotations

import bisect
import logging
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, NamedTuple

from PyQt6.QtCore import (QAbstractListModel, QDate, QLocale, QModelIndex, QPoint, QRect, QRectF, QSize,
                          QSortFilterProxyModel, Qt, pyqtSignal)
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QLineEdit, QListView, QStyle,
                             QStyledItemDelegate)

from tilauscope.tilauscope_types import THEME, get_agtron_color

if TYPE_CHECKING:
    from collections.abc import Mapping

    from tilauscope.alogmanager import AlogMetadata

_log = logging.getLogger(__name__)

#: The data role carrying a row's RoastRow.
ROW_ROLE = Qt.ItemDataRole.UserRole + 1

SORT_RECENT = 'recent'
SORT_OLDEST = 'oldest'
SORT_COFFEE = 'coffee'
SORT_MODES = (SORT_RECENT, SORT_OLDEST, SORT_COFFEE)

#: Magnifier for the search field, as a header_icons.make_icon template.
SVG_SEARCH = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
    '<circle cx="7" cy="7" r="4.5" fill="none" stroke="{color}" stroke-width="1.5"/>'
    '<line x1="10.4" y1="10.4" x2="14" y2="14" stroke="{color}" stroke-width="1.5" '
    'stroke-linecap="round"/></svg>'
)


def fold(text: str) -> str:
    """Lower case without accents, for matching: "Café" and "cafe" are one word.

    NFD, not NFKD: the compatibility forms rewrite symbols such as µ.
    """
    decomposed = unicodedata.normalize('NFD', text or '')
    return ''.join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def query_tokens(text: str) -> list[str]:
    """The words of a search; a roast matches when it contains every one."""
    return fold(text).split()


class BeanFacts(NamedTuple):
    """What a row needs from a green bean record — plain values, safe off the GUI thread."""
    name: str
    process: str
    crop: int
    farm: str
    country: str


@dataclass(frozen=True, slots=True)
class RoastRow:
    """One roast as the list shows it."""
    fname: str
    epoch: int              # roast date in seconds; 0 when none could be read
    label: str              # the name shown above the curve
    title: str              # the coffee
    group: str              # the coffee's identity: its bean record, else its folded title
    process: str = ''
    crop: int = 0
    batch: str = ''         # "#44", or "" when the roast has no batch number
    weight_in_g: float = 0.0
    weight_out_g: float = 0.0
    colour: float = 0.0     # ground colour when measured, else whole bean; 0 = none
    colour_ground: bool = False   # the colour is a ground reading
    indexed: bool = False   # the roast index knows this file: weights and colour are read
    search: str = ''        # folded text a search matches against

    @property
    def missing_result(self) -> bool:
        """Neither a roasted weight nor a colour — the result form was never filled."""
        return self.indexed and self.weight_out_g <= 0 and self.colour <= 0

    def matches(self, tokens: list[str]) -> bool:
        return all(token in self.search for token in tokens)


def make_row(fname: str, epoch: int, label: str, title: str,
             meta: AlogMetadata | None, beans: Mapping[str, BeanFacts]) -> RoastRow:
    """A list row from the scan's name and date, the index entry and the bean records."""
    bean = beans.get(meta.uuid) if meta is not None and meta.uuid else None
    if bean is not None and bean.name.strip():
        title = bean.name.strip()
        group = f'bean:{meta.uuid}' if meta is not None else ''
    else:
        group = f'title:{fold(title)}'
    process = bean.process.strip() if bean is not None else ''
    crop = int(bean.crop or 0) if bean is not None else 0
    batch = ''
    colour = weight_in = weight_out = 0.0
    colour_ground = False
    if meta is not None:
        if meta.batch_nr > 0:
            batch = f"#{(meta.batch_prefix or '').lstrip('#')}{meta.batch_nr}"
        # Ground when measured, else whole bean — never the lighter of the two.
        colour = meta.ground_color if meta.ground_color > 0 else max(meta.whole_color, 0.0)
        colour_ground = meta.ground_color > 0
        weight_in, weight_out = meta.weight_in_g, meta.weight_out_g
    words = (title, process, str(crop) if crop else '',
             bean.farm if bean is not None else '', bean.country if bean is not None else '', batch)
    return RoastRow(fname=fname, epoch=epoch, label=label, title=title, group=group,
                    process=process, crop=crop, batch=batch, weight_in_g=weight_in,
                    weight_out_g=weight_out, colour=colour, colour_ground=colour_ground,
                    indexed=meta is not None,
                    search=fold(' '.join(word for word in words if word)))


def day_of(epoch: int) -> date | None:
    if epoch <= 0:
        return None
    try:
        return datetime.fromtimestamp(epoch).date()
    except (OSError, OverflowError, ValueError):
        return None


def day_label(day: date | None, today: date, locale: QLocale | None = None) -> str:
    """Today, Yesterday, or the day by name — with its year only when not this year's."""
    if day is None:
        return QApplication.translate('tilauscope_beancave', 'No date')
    if day == today:
        return QApplication.translate('tilauscope_beancave', 'Today')
    if day == today - timedelta(days=1):
        return QApplication.translate('tilauscope_beancave', 'Yesterday')
    pattern = 'dddd d MMMM' if day.year == today.year else 'dddd d MMMM yyyy'
    text = (locale or QLocale()).toString(QDate(day.year, day.month, day.day), pattern)
    return text[:1].upper() + text[1:]


def roast_count_text(count: int) -> str:
    if count == 1:
        return QApplication.translate('tilauscope_beancave', '1 roast')
    return QApplication.translate('tilauscope_beancave', '{0} roasts').format(count)


class RoastListModel(QAbstractListModel):
    """Every roast of the folder, in the order the scan found them."""

    def __init__(self, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._rows: list[RoastRow] = []
        self._row_of: dict[str, int] = {}

    def set_rows(self, rows: list[RoastRow]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self._row_of = {row.fname: i for i, row in enumerate(self._rows)}
        self.endResetModel()

    def rows(self) -> list[RoastRow]:
        return self._rows

    def row_of(self, fname: str) -> int:
        return self._row_of.get(fname, -1)

    def rowCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        return 0 if parent is not None and parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: ANN201
        # A Qt virtual: an exception escaping it closes the application.
        try:
            if not index.isValid() or not 0 <= index.row() < len(self._rows):
                return None
            row = self._rows[index.row()]
            if role == ROW_ROLE:
                return row
            if role == Qt.ItemDataRole.DisplayRole:
                return row.title
            if role == Qt.ItemDataRole.ToolTipRole:
                return row.fname
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _log.exception('roast list data')
        return None


class RoastFilterProxy(QSortFilterProxyModel):
    """The search, the coffee filter and the order — and the groups they produce."""

    def __init__(self, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._tokens: list[str] = []
        self._group = ''
        self._sort = SORT_RECENT
        self._locale = QLocale()
        self._starts: list[int] | None = None
        self._headings: dict[int, tuple[str, str]] = {}
        self._texts: dict[int, tuple[str, str, str, str]] = {}
        for signal in (self.modelReset, self.layoutChanged, self.rowsInserted, self.rowsRemoved):
            signal.connect(self._forget_groups)

    # ── what is shown ────────────────────────────────────────────────────────

    def set_query(self, text: str) -> None:
        tokens = query_tokens(text)
        if tokens != self._tokens:
            self._tokens = tokens
            self.invalidateRowsFilter()

    def set_group(self, group: str) -> None:
        if group != self._group:
            self._group = group
            self.invalidateRowsFilter()

    def set_sort(self, mode: str) -> None:
        self._sort = mode if mode in SORT_MODES else SORT_RECENT
        self.invalidate()
        self.sort(0, Qt.SortOrder.AscendingOrder)

    def sort_mode(self) -> str:
        return self._sort

    def set_locale(self, locale: QLocale) -> None:
        """The language day names are written in — the interface's, not the system's."""
        self._locale = locale
        self._forget_groups()

    def display_locale(self) -> QLocale:
        return self._locale

    def is_filtered(self) -> bool:
        return bool(self._tokens or self._group)

    def row_at(self, proxy_row: int) -> RoastRow:
        return self.sourceModel().rows()[self.mapToSource(self.index(proxy_row, 0)).row()]

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:  # noqa: N802
        try:
            row = self.sourceModel().rows()[source_row]
            return (not self._group or row.group == self._group) and row.matches(self._tokens)
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _log.exception('roast list filter')
            return True

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:  # noqa: N802
        try:
            rows = self.sourceModel().rows()
            a, b = rows[left.row()], rows[right.row()]
            if self._sort == SORT_OLDEST:
                return (a.epoch, a.fname) < (b.epoch, b.fname)
            if self._sort == SORT_COFFEE:
                return ((fold(a.title), a.crop, a.group, -a.epoch, a.fname)
                        < (fold(b.title), b.crop, b.group, -b.epoch, b.fname))
            return (-a.epoch, a.fname) < (-b.epoch, b.fname)
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _log.exception('roast list order')
            return False

    # ── groups ───────────────────────────────────────────────────────────────

    def _forget_groups(self, *_args) -> None:  # noqa: ANN002
        self._starts = None
        self._headings.clear()
        self._texts.clear()

    def _key(self, row: RoastRow):  # noqa: ANN202
        return row.group if self._sort == SORT_COFFEE else day_of(row.epoch)

    def _group_starts(self) -> list[int]:
        """First row of every group, top to bottom, with each group's heading."""
        if self._starts is None:
            starts: list[int] = []
            sizes: dict[int, int] = {}
            first_rows: dict[int, RoastRow] = {}
            previous: object = object()
            for proxy_row in range(self.rowCount()):
                row = self.row_at(proxy_row)
                key = self._key(row)
                if not starts or key != previous:
                    starts.append(proxy_row)
                    sizes[proxy_row] = 0
                    first_rows[proxy_row] = row
                    previous = key
                sizes[starts[-1]] += 1
            today = date.today()
            for first in starts:
                row = first_rows[first]
                if self._sort == SORT_COFFEE:
                    label = f'{row.title} · {row.crop}' if row.crop else row.title
                else:
                    label = day_label(day_of(row.epoch), today, self._locale)
                self._headings[first] = (label, roast_count_text(sizes[first]))
            self._starts = starts
        return self._starts

    def group_size(self, proxy_row: int) -> int:
        """Roasts in the group this row opens; 0 when the row opens none."""
        starts = self._group_starts()
        i = bisect.bisect_left(starts, proxy_row)
        if i >= len(starts) or starts[i] != proxy_row:
            return 0
        end = starts[i + 1] if i + 1 < len(starts) else self.rowCount()
        return end - proxy_row

    def group_bounds(self, proxy_row: int) -> tuple[int, int]:
        """(first row of this row's group, first row of the next group or -1)."""
        starts = self._group_starts()
        i = bisect.bisect_right(starts, proxy_row) - 1
        first = starts[i] if i >= 0 else 0
        following = starts[i + 1] if i + 1 < len(starts) else -1
        return first, following

    def heading(self, proxy_row: int) -> tuple[str, str]:
        self._group_starts()
        return self._headings.get(proxy_row, ('', ''))

    def row_text(self, proxy_row: int) -> tuple[str, str, str, str]:
        """(first line, its right side, second line, its right side) for one row."""
        text = self._texts.get(proxy_row)
        if text is None:
            row = self.row_at(proxy_row)
            when = datetime.fromtimestamp(row.epoch).strftime('%H:%M') if row.epoch > 0 else ''
            weight = f'{row.weight_in_g:.0f} g' if row.weight_in_g > 0 else ''
            if self._sort == SORT_COFFEE:
                # The heading names the coffee: the row names the day, and the
                # second line has room for what the roast turned the batch into.
                if weight and row.weight_out_g > 0:
                    weight = f'{weight} → {row.weight_out_g:.0f} g'
                first = day_label(day_of(row.epoch), date.today(), self._locale)
                second = ' · '.join(part for part in (row.process, weight) if part)
            else:
                first = row.title
                crop = str(row.crop) if row.crop else ''
                second = ' · '.join(part for part in (row.process, crop, weight) if part)
            text = (first, when, second, row.batch)
            self._texts[proxy_row] = text
        return text


class RoastRowDelegate(QStyledItemDelegate):
    """Paints one roast on two lines, and its group's heading above the first one."""

    ROW_H = 50
    HEAD_H = 28

    def __init__(self, proxy: RoastFilterProxy, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._proxy = proxy
        self._reported = False
        base = QApplication.font()
        self._font_title = self._font(base, 13, QFont.Weight.DemiBold)
        self._font_line = self._font(base, 11, QFont.Weight.Normal)
        self._font_head = self._font(base, 11, QFont.Weight.DemiBold)
        self._font_badge = self._font(base, 10, QFont.Weight.DemiBold)
        self._no_result = QApplication.translate('tilauscope_beancave', 'No result')

    @staticmethod
    def _font(base: QFont, pixels: int, weight: QFont.Weight) -> QFont:
        font = QFont(base)
        font.setPixelSize(pixels)
        font.setWeight(weight)
        return font

    @staticmethod
    def _colour(token: str, alpha: int = 255) -> QColor:
        colour = QColor(THEME[token])
        colour.setAlpha(alpha)
        return colour

    def _report(self, what: str) -> None:
        if not self._reported:
            self._reported = True
            _log.exception(what)

    def sizeHint(self, option, index: QModelIndex) -> QSize:  # noqa: ANN001, N802
        try:
            head = self.HEAD_H if self._proxy.group_size(index.row()) else 0
            return QSize(option.rect.width(), self.ROW_H + head)
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            self._report('roast list row size')
            return QSize(0, self.ROW_H)

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:  # noqa: ANN001
        painter.save()
        try:
            self._paint_row(painter, option, index.row())
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            self._report('roast list row paint')
        finally:
            painter.restore()

    def paint_heading(self, painter: QPainter, rect: QRect, label: str, count: str) -> None:
        # Opaque: the pinned copy at the top of the list covers the rows under it.
        painter.fillRect(rect, self._colour('SURFACE'))
        left, right = rect.left() + 12, rect.right() - 12
        painter.setFont(self._font_line)
        count_w = QFontMetrics(self._font_line).horizontalAdvance(count)
        painter.setPen(self._colour('OVERLAY0'))
        painter.drawText(QRect(right - count_w, rect.top(), count_w, rect.height()),
                         int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight), count)
        metrics = QFontMetrics(self._font_head)
        label = metrics.elidedText(label, Qt.TextElideMode.ElideRight, max(0, right - count_w - 16 - left))
        label_w = metrics.horizontalAdvance(label)
        painter.setFont(self._font_head)
        painter.setPen(self._colour('SUBTEXT'))
        painter.drawText(QRect(left, rect.top(), label_w, rect.height()),
                         int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), label)
        rule_from, rule_to = left + label_w + 8, right - count_w - 8
        if rule_to - rule_from > 12:
            pen = QPen(self._colour('BORDER'))
            pen.setStyle(Qt.PenStyle.DotLine)
            painter.setPen(pen)
            mid = rect.top() + rect.height() // 2 + 1
            painter.drawLine(rule_from, mid, rule_to, mid)

    def _paint_row(self, painter: QPainter, option, proxy_row: int) -> None:  # noqa: ANN001
        rect = QRect(option.rect)
        if self._proxy.group_size(proxy_row):
            self.paint_heading(painter, QRect(rect.left(), rect.top(), rect.width(), self.HEAD_H),
                               *self._proxy.heading(proxy_row))
            rect.setTop(rect.top() + self.HEAD_H)
        row = self._proxy.row_at(proxy_row)
        first, when, second, batch = self._proxy.row_text(proxy_row)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        card = QRectF(rect.adjusted(4, 2, -4, -2))
        if option.state & QStyle.StateFlag.State_Selected:
            painter.setPen(QPen(self._colour('ACCENT', 110), 1))
            painter.setBrush(self._colour('ACCENT', 38))
            painter.drawRoundedRect(card, 6, 6)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._colour('ACCENT'))
            painter.drawRoundedRect(QRectF(card.left(), card.top() + 6, 3, card.height() - 12), 1.5, 1.5)
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._colour('BORDER'))
            painter.drawRoundedRect(card, 6, 6)

        left, right = rect.left() + 30, rect.right() - 12
        line1 = QRect(left, rect.top() + 7, right - left, 18)
        line2 = QRect(left, rect.top() + 26, right - left, 16)

        # The roast colour, when one was measured; a ring when none was. Both
        # readings take their colour from the one roast scale, so a number and
        # its dot always say the same thing. A ground reading fills the dot; a
        # whole-bean reading, which runs a shade darker on the same meter, is
        # drawn as a ring of that colour.
        dot = QRectF(rect.left() + 14, line1.center().y() - 4, 8, 8)
        if row.colour > 0:
            shade = QColor(get_agtron_color(row.colour))
            if row.colour_ground:
                painter.setPen(QPen(self._colour('OVERLAY0', 150), 1))
                painter.setBrush(shade)
            else:
                painter.setPen(QPen(shade, 1.6))
                painter.setBrush(Qt.BrushStyle.NoBrush)
        else:
            painter.setPen(QPen(self._colour('OVERLAY0'), 1.2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(dot)

        align_left = int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        align_right = int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)

        line_metrics = QFontMetrics(self._font_line)
        when_w = line_metrics.horizontalAdvance(when)
        painter.setFont(self._font_line)
        painter.setPen(self._colour('SUBTEXT'))
        painter.drawText(line1, align_right, when)

        badge_w = 0
        badge_metrics = QFontMetrics(self._font_badge)
        if row.missing_result:
            badge_w = badge_metrics.horizontalAdvance(self._no_result) + 12
        title_room = max(0, line1.width() - when_w - 10 - (badge_w + 8 if badge_w else 0))
        title_metrics = QFontMetrics(self._font_title)
        title = title_metrics.elidedText(first, Qt.TextElideMode.ElideRight, title_room)
        painter.setFont(self._font_title)
        painter.setPen(self._colour('TEXT'))
        painter.drawText(line1, align_left, title)

        if badge_w:
            badge = QRectF(left + title_metrics.horizontalAdvance(title) + 8,
                           line1.center().y() - 8, badge_w, 16)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._colour('WARNING', 40))
            painter.drawRoundedRect(badge, 8, 8)
            painter.setFont(self._font_badge)
            painter.setPen(self._colour('WARNING'))
            painter.drawText(badge, int(Qt.AlignmentFlag.AlignCenter), self._no_result)

        batch_w = line_metrics.horizontalAdvance(batch)
        painter.setFont(self._font_line)
        painter.setPen(self._colour('OVERLAY0'))
        painter.drawText(line2, align_right, batch)
        painter.setPen(self._colour('SUBTEXT'))
        painter.drawText(line2, align_left, line_metrics.elidedText(
            second, Qt.TextElideMode.ElideRight, max(0, line2.width() - batch_w - 10)))


class RoastListView(QListView):
    """The list itself: keeps the current group's heading pinned at the top."""

    def __init__(self, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._reported = False
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setUniformItemSizes(False)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        # Scrolling moves painted pixels; the pinned heading must be drawn afresh.
        self.verticalScrollBar().valueChanged.connect(lambda _value: self.viewport().update())

    def _report(self, what: str) -> None:
        if not self._reported:
            self._reported = True
            _log.exception(what)

    def _pinned_heading(self) -> tuple[QRect, int] | None:
        """Where the pinned heading sits and which group it names, or None when
        the top group's own heading is still on screen."""
        proxy = self.model()
        delegate = self.itemDelegate()
        if not isinstance(proxy, RoastFilterProxy) or not isinstance(delegate, RoastRowDelegate):
            return None
        top = self.indexAt(QPoint(4, 1))
        if not top.isValid():
            return None
        first, following = proxy.group_bounds(top.row())
        if self.visualRect(proxy.index(first, 0)).top() >= 0:
            return None
        y = 0
        if following >= 0:
            next_top = self.visualRect(proxy.index(following, 0)).top()
            if next_top < delegate.HEAD_H:
                y = next_top - delegate.HEAD_H   # the next heading pushes this one up
        return QRect(0, y, self.viewport().width(), delegate.HEAD_H), first

    def paintEvent(self, event) -> None:  # noqa: ANN001, N802
        super().paintEvent(event)
        painter = None
        try:
            pinned = self._pinned_heading()
            if pinned is not None:
                rect, first = pinned
                painter = QPainter(self.viewport())
                self.itemDelegate().paint_heading(painter, rect, *self.model().heading(first))
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            self._report('roast list pinned heading')
        finally:
            if painter is not None and painter.isActive():
                painter.end()

    def _on_heading(self, pos: QPoint) -> bool:
        pinned = self._pinned_heading()
        if pinned is not None and pinned[0].contains(pos):
            return True
        index = self.indexAt(pos)
        proxy = self.model()
        if not index.isValid() or not isinstance(proxy, RoastFilterProxy) or not proxy.group_size(index.row()):
            return False
        return pos.y() - self.visualRect(index).top() < RoastRowDelegate.HEAD_H

    def mousePressEvent(self, event) -> None:  # noqa: ANN001, N802
        try:
            if self._on_heading(event.position().toPoint()):
                event.accept()   # a heading is not a roast: nothing to select
                return
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            self._report('roast list heading click')
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: ANN001, N802
        try:
            if self._on_heading(event.position().toPoint()):
                event.accept()
                return
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            self._report('roast list heading click')
        super().mouseDoubleClickEvent(event)


class RoastSearchField(QLineEdit):
    """The search box: Esc empties it before it closes anything, ↓ moves to the list."""

    move_to_list = pyqtSignal()

    def keyPressEvent(self, event) -> None:  # noqa: ANN001, N802
        try:
            if event.key() == Qt.Key.Key_Escape and self.text():
                self.clear()
                event.accept()
                return
            if event.key() == Qt.Key.Key_Down:
                self.move_to_list.emit()
                event.accept()
                return
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _log.exception('roast search key')
        super().keyPressEvent(event)

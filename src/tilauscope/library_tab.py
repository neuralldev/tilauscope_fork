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

"""BeanCave › Library: browse the roasts other roasters published, import one, withdraw yours.

A roast is published from the Roasts tab, on the roast itself: good or not, it tells the others what happened.

Every call to the relay runs on a thread of its own and answers through
signals; nothing is fetched before the tab is first shown. The list comes a
page at a time, searched and filtered by the relay. Spec:
wiki/CoffeeLibrary-Spec.md §5.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any, Final

from PyQt6.QtCore import QDate, QLocale, QObject, QRect, QRectF, QSettings, QSize, Qt, QThread, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import (QApplication, QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                             QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)

from tilaucore import coffee_share as core
from tilaucore.beans import GreenBean
from tilaucore.coffee_library import LIBRARY_URL, Card, Library, LibraryError, Page, Sign, card_from
from tilaucore.roasters import canonical_roaster_name
from tilaucore.ror import RoRSettings, rate_of_rise
from tilauscope import library_identity
from tilauscope.beancave_catalogue import svg_pixmap
from tilauscope.cave.roast_list import SVG_SEARCH
from tilauscope.header_icons import SVG_PROG_DOWNLOAD, SVG_PROG_UPLOAD, make_icon
from tilauscope.theme_qss import base_qss, restyle, tint
from tilauscope.tilauscope_types import THEME, park_until_finished, show_styled_message
from tilauscope.widgets.card_dialog import CardDialog, card_button, card_label
from tilauscope.widgets.flow_layout import FlowLayout

_log = logging.getLogger(__name__)

#: A roast card's download runs as the task "card:<id>": several may be on their way at once.
_CARD: Final[str] = "card"
#: Roast card images kept drawn (about 23 MB each); the parsed roasts are all kept.
_IMAGES_KEPT: Final[int] = 6
#: A page of the list runs as "page:<query>" (the first one, replacing the list) or "more:<query>".
_PAGE, _MORE = "page", "more"
#: The search is sent once the typing has paused this long.
_SEARCH_PAUSE_MS: Final[int] = 400
#: The next page is asked for once the list is scrolled this close to its end.
_MORE_MARGIN_PX: Final[int] = 120

#: The ids this installation published: the relay never says who published what (§3.2).
PUBLISHED_KEY: Final[str] = "tilauscope/library_published"

_SVG_MACHINE = "M12 4.5a7.5 7.5 0 1 0 0 15a7.5 7.5 0 1 0 0-15M12 4.5v15M4.5 12h15"
_SVG_CHECK = "M5 12.5l4.5 4.5L19 7.5"
_SVG_LOCK = "M5 11h14v9H5zM8 11V8a4 4 0 0 1 8 0v3"

_QSS = f"""
    QFrame#libPanel {{ background:{THEME['SURFACE']}; border:none; border-radius:18px; }}
    QFrame#libRow {{ background:transparent; border:1px solid transparent; border-radius:10px; }}
    QFrame#libRow:hover {{ background:{THEME['SURFACE']}; }}
    QFrame#libRow[selected="true"] {{ background:{tint('ACCENT', 0.10)}; border:1px solid {tint('ACCENT', 0.5)}; }}
    QFrame#libZone {{ background:{THEME['SURFACE']}; border:1px solid {THEME['BORDER']}; border-radius:16px; }}
    QFrame#libZone[accent="true"] {{ border:1px solid {tint('ACCENT', 0.45)}; }}
    QFrame#libZone QWidget, QFrame#libRow QWidget, QFrame#libPanel QWidget {{ background:transparent; }}
    QLabel#libEyebrow {{ color:{THEME['OVERLAY0']}; font-size:11px; font-weight:600; letter-spacing:2px; }}
    QLabel#libEyebrow[accent="true"] {{ color:{THEME['ACCENT']}; }}
    QLabel#libTag {{ color:{THEME['MAUVE']}; border:1px solid {THEME['MAUVE']}; border-radius:4px;
                     font-size:10px; font-weight:700; letter-spacing:1px; padding:1px 6px; }}
    QLabel#libChip {{ color:{THEME['TEXT']}; border:1px solid {THEME['SURFACE1']}; border-radius:12px;
                      font-size:13px; padding:3px 10px; }}
    QLabel#libToast {{ background:{THEME['BORDER']}; color:{THEME['TEXT']}; border-radius:14px;
                       font-size:15px; padding:10px 18px; }}
    QLineEdit#libSearch {{ background:{THEME['SURFACE']}; color:{THEME['TEXT']}; border:1px solid {THEME['SURFACE1']}; border-radius:12px;
                           font-size:15px; padding:0 10px; min-height:42px; }}
    QLineEdit#libSearch:focus {{ border:1px solid {THEME['ACCENT']}; }}
    QPushButton#libChipButton {{ background:transparent; color:{THEME['SUBTEXT']}; border:1px solid {THEME['SURFACE1']};
                                 border-radius:12px; font-size:14px; padding:0 14px; min-height:42px; }}
    QPushButton#libChipButton:hover {{ color:{THEME['TEXT']}; }}
    QPushButton#libChipButton:checked {{ color:{THEME['BG']}; border-color:{THEME['ACCENT']};
                                         background:{THEME['ACCENT']}; font-weight:600; }}
    QPushButton#libChipButton:disabled {{ color:{THEME['OVERLAY0']}; }}
    QPushButton#libTonal {{ background:{tint('ACCENT', 0.16)}; color:{THEME['ACCENT']}; border:none; border-radius:14px;
                            font-size:15px; font-weight:700; min-height:48px; padding:0 22px; }}
    QPushButton#libTonal:hover {{ background:{tint('ACCENT', 0.24)}; }}
    QPushButton#libTonal:disabled {{ color:{THEME['OVERLAY0']}; background:{THEME['BORDER']}; }}
    QPushButton#libGhost {{ background:transparent; color:{THEME['TEXT']}; border:1px solid {THEME['SURFACE1']};
                            border-radius:14px; font-size:16px; font-weight:600; min-height:50px; padding:0 20px; }}
    QPushButton#libGhost:hover {{ background:{THEME['BORDER']}; }}
    QPushButton#libGhost:disabled {{ color:{THEME['OVERLAY0']}; }}
    QPushButton#libMore {{ background:transparent; color:{THEME['OVERLAY0']}; border:none; font-size:12px;
                           padding:10px 4px; text-align:left; }}
    QPushButton#libMore:hover {{ color:{THEME['TEXT']}; }}
    QPushButton#libMore:disabled {{ color:{THEME['OVERLAY0']}; }}
"""


# ── small pieces ────────────────────────────────────────────────────────────

def published_ids() -> list[str]:
    return [str(i) for i in QSettings().value(PUBLISHED_KEY, [], type=list) or []]


def _set_published(ids: list[str]) -> None:
    QSettings().setValue(PUBLISHED_KEY, ids)


def _label(text: str, name: str = "", css: str = "", wrap: bool = False) -> QLabel:
    label = QLabel(text)
    if name:
        label.setObjectName(name)
    if css:
        label.setStyleSheet(css)
    label.setWordWrap(wrap)
    return label


def _icon_label(path_d: str, colour: str, size: int) -> QLabel:
    label = QLabel()
    label.setPixmap(svg_pixmap(path_d, colour, size, 2.2))
    label.setFixedSize(size, size)
    return label




def _where(card: Card) -> str:
    return " · ".join(t for t in (card.country, card.process) if t)


def _flagged(widget: QWidget, name: str, on: bool) -> None:
    widget.setProperty(name, "true" if on else "false")
    restyle(widget)


def verdict_sentence(verdict: str) -> str:
    """Their tasting in words; '' when they did not taste it."""
    if verdict == "yes":
        return QApplication.translate("tilauscope_beancave", "Liked it · would roast it the same way")
    if verdict == "almost":
        return QApplication.translate("tilauscope_beancave", "Almost · would change a little")
    if verdict == "no":
        return QApplication.translate("tilauscope_beancave", "Did not like it · would roast it differently")
    return ""


def failure_sentence(task: str, kind: str) -> str:
    """What happened and what to do, for a LibraryError kind (or 'local': this computer failed) during ``task``."""
    if task == "card" and kind == "offline":
        return QApplication.translate("tilauscope_beancave", "The roast card could not be loaded: the library cannot be reached. Check the internet connection, then select the roast again.")
    if task == "card" and kind == "unknown":
        return QApplication.translate("tilauscope_beancave", "The roast card could not be loaded: its author withdrew this roast from the library.")
    if task == "card":
        return QApplication.translate("tilauscope_beancave", "The roast card could not be loaded. Select the roast again to try once more.")
    if kind == "offline":
        return QApplication.translate("tilauscope_beancave", "The library cannot be reached. Check the internet connection, then try again.")
    if kind == "rate":
        return QApplication.translate("tilauscope_beancave", "The library takes a limited number of coffees from each computer per day. Try again tomorrow.")
    if kind == "local":
        return QApplication.translate("tilauscope_beancave", "TilauScope could not write the coffee on this computer. Check the free disk space, then try again.")
    if kind == "too_large" and task == "publish":
        return QApplication.translate("tilauscope_beancave", "This roast is too large for the library and cannot be published.")
    if kind == "too_large":
        return QApplication.translate("tilauscope_beancave", "This coffee is too large to import safely. Choose another coffee.")
    if kind == "unknown" and task == "import":
        return QApplication.translate("tilauscope_beancave", "This coffee is no longer in the library: its author withdrew it. The list is now up to date.")
    if task in ("publish", "withdraw"):
        return QApplication.translate("tilauscope_beancave", "The library did not accept the request. Check that this computer's date and time are correct, then try again.")
    return QApplication.translate("tilauscope_beancave", "The library sent an answer TilauScope cannot read. Try again later, or update TilauScope.")


def _roast_day(day: str) -> str:
    """The roast's day as the operator's language writes a short date: 15 Feb 2026."""
    return QLocale().toString(QDate.fromString(day, Qt.DateFormat.ISODate), "d MMM yyyy")


class _Elided(QLabel):
    """One line of text, cut with an ellipsis at the width it is given."""

    def __init__(self, text: str, css: str) -> None:
        super().__init__(text)
        self._full = text
        self.setStyleSheet(css)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def full_text(self) -> str:
        return self._full

    def resizeEvent(self, event: Any) -> None:  # noqa: N802
        # A Qt virtual: an exception escaping it would close the application.
        try:
            super().resizeEvent(event)
            self.setText(self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, self.width()))
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _log.exception("library label not elided")


class _Row(QFrame):
    """One roast in the list: coffee and day, origin, machine."""

    clicked = pyqtSignal(str)

    def __init__(self, card: Card, mine: bool) -> None:
        super().__init__()
        self.setObjectName("libRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.card = card
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(3)
        title = QHBoxLayout()
        title.setSpacing(8)
        title.addWidget(_Elided(card.name, f"color:{THEME['TEXT']};font-size:14px;font-weight:700;"), 1)
        title.addWidget(_label(_roast_day(card.roasted) if card.roasted else "", css=f"color:{THEME['SUBTEXT']};font-size:12px;"))
        lay.addLayout(title)
        lay.addWidget(_Elided(_where(card), f"color:{THEME['SUBTEXT']};font-size:12px;"))
        meta = QHBoxLayout()
        meta.setSpacing(8)
        meta.addWidget(_Elided(canonical_roaster_name(card.roaster), f"color:{THEME['OVERLAY0']};font-size:12px;font-style:italic;"), 1)
        if mine:
            meta.addWidget(_label(QApplication.translate("tilauscope_beancave", "MINE"), "libTag"))
        lay.addLayout(meta)
        self.set_selected(False)

    def set_selected(self, on: bool) -> None:
        _flagged(self, "selected", on)

    def mouseReleaseEvent(self, event: Any) -> None:  # noqa: N802
        # A Qt virtual: an exception escaping it would close the application.
        try:
            if event.button() == Qt.MouseButton.LeftButton:
                self.clicked.emit(self.card.id)
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _log.exception("library row click failed")


class _CardView(QWidget):
    """The roast card scaled to the width it is given, 16:9, or a sentence in its place."""

    def __init__(self) -> None:
        super().__init__()
        self._image: QImage | None = None
        self._scaled: QPixmap | None = None
        self._text = ""
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.setMinimumSize(320, 180)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return round(width * 9 / 16)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(640, 360)

    def image(self) -> QImage | None:
        return self._image

    def message(self) -> str:
        return self._text

    def show_image(self, image: QImage) -> None:
        if image is self._image:
            return
        self._image, self._scaled, self._text = image, None, ""
        self.update()

    def show_message(self, text: str) -> None:
        self._image, self._scaled, self._text = None, None, text
        self.update()

    def _frame(self) -> QRect:
        width = min(self.width(), round(self.height() * 16 / 9))
        height = round(width * 9 / 16)
        return QRect((self.width() - width) // 2, 0, width, height)

    def paintEvent(self, _event: Any) -> None:  # noqa: N802
        # A Qt virtual: an exception escaping it would close the application.
        try:
            frame = self._frame()
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            outline = QPainterPath()
            outline.addRoundedRect(QRectF(frame).adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)
            painter.fillPath(outline, QColor(THEME['SURFACE']))
            if self._image is not None and not self._image.isNull():
                ratio = self.devicePixelRatioF()
                wanted = QSize(round(frame.width() * ratio), round(frame.height() * ratio))
                if self._scaled is None or self._scaled.size() != wanted:
                    self._scaled = QPixmap.fromImage(self._image.scaled(
                        wanted, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation))
                    self._scaled.setDevicePixelRatio(ratio)
                painter.setClipPath(outline)
                painter.drawPixmap(frame.topLeft(), self._scaled)
                painter.setClipping(False)
            elif self._text:
                painter.setPen(QColor(THEME['SUBTEXT']))
                font = painter.font()
                font.setPixelSize(14)
                painter.setFont(font)
                painter.drawText(frame.adjusted(40, 0, -40, 0),
                                 int(Qt.AlignmentFlag.AlignCenter) | int(Qt.TextFlag.TextWordWrap), self._text)
            painter.setPen(QPen(QColor(THEME['BORDER']), 1))
            painter.drawPath(outline)
            painter.end()
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _log.exception("library roast card not drawn")


def _roast_ror(roast: dict[str, Any]) -> list[float | None]:
    """The bean's RoR from CHARGE on, in the roast's own unit, over the 20 s window."""
    index = roast.get("timeindex") or [-1]
    charge = index[0] if isinstance(index[0], int) and index[0] > 0 else 0
    factor = 1.8 if roast.get("mode") == "F" else 1.0
    return rate_of_rise(roast.get("timex") or [], roast.get("temp2") or [],
                        RoRSettings(limit_min=-10 * factor, limit_max=45 * factor), start=charge)


def _load_card(library: Library, coffee_id: str, version: str, build: int) -> tuple[str, dict[str, Any], GreenBean, list[float | None]]:
    """Off the GUI thread, no Qt: the published roast of ``coffee_id``, its coffee and its RoR.

    The package lands in a folder of its own, gone once it has been read, whatever happened."""
    folder = Path(tempfile.mkdtemp(prefix="tilau-library-card-"))
    try:
        package = core.read_package(library.download(coffee_id, folder), version=version, build=build)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    roast = next(iter(package.roasts.values()))      # a published coffee holds the one roast it was published with
    return coffee_id, roast, package.bean, _roast_ror(roast)


def _zone(eyebrow: str = "", accent: bool = False) -> tuple[QFrame, QVBoxLayout]:
    zone = QFrame()
    zone.setObjectName("libZone")
    _flagged(zone, "accent", accent)
    lay = QVBoxLayout(zone)
    lay.setContentsMargins(14, 12, 14, 12)
    lay.setSpacing(8)
    if eyebrow:
        head = _label(eyebrow, "libEyebrow")
        _flagged(head, "accent", accent)
        lay.addWidget(head)
    return zone, lay


class _Job(QObject):
    """One call to the relay, off the GUI thread; answers by signal only."""

    done = pyqtSignal(str, object)
    failed = pyqtSignal(str, str)

    def __init__(self, task: str, call: Callable[[], Any]) -> None:
        super().__init__()
        self._task, self._call = task, call

    @pyqtSlot()
    def run(self) -> None:
        try:
            result = self._call()
        except LibraryError as e:
            self.failed.emit(self._task, e.kind)
            return
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _log.exception("library %s failed on this computer", self._task)
            self.failed.emit(self._task, "local")
            return
        self.done.emit(self._task, result)


# ── publish dialog ──────────────────────────────────────────────────────────

class PublishDialog(CardDialog):
    """What goes to the library and what stays here; nothing leaves before the agreement is ticked."""

    def __init__(self, parent: QWidget | None, name: str, tasting: bool, brewing: bool) -> None:
        super().__init__(parent, QApplication.translate("tilauscope_beancave", "Publish this roast of {0} to the library").format(name))
        self.setFixedWidth(720)
        lay = self.page()
        goes, goes_lay = _zone(QApplication.translate("tilauscope_beancave", "GOES TO THE LIBRARY"), accent=True)
        rows = [QApplication.translate("tilauscope_beancave", "The coffee: origin, process, flavours"),
                QApplication.translate("tilauscope_beancave", "This roast and its curve")]
        if tasting:
            rows.append(QApplication.translate("tilauscope_beancave", "Your tasting"))
        if brewing:
            rows.append(QApplication.translate("tilauscope_beancave", "Brew settings"))
        for text in rows:
            goes_lay.addLayout(self._line(_SVG_CHECK, THEME['SUCCESS'], text))
        goes_lay.addStretch()
        stays, stays_lay = _zone(QApplication.translate("tilauscope_beancave", "STAYS ON THIS COMPUTER"))
        for text in (QApplication.translate("tilauscope_beancave", "Your name and organisation"),
                     QApplication.translate("tilauscope_beancave", "Stock, sacks, price"),
                     QApplication.translate("tilauscope_beancave", "Room conditions, altitude"),
                     QApplication.translate("tilauscope_beancave", "File locations, alarms")):
            stays_lay.addLayout(self._line(_SVG_LOCK, THEME['SUBTEXT'], text))
        stays_lay.addStretch()
        two = QHBoxLayout()
        two.setSpacing(12)
        two.addWidget(goes, 1)
        two.addWidget(stays, 1)
        lay.addLayout(two)
        lay.addWidget(card_label(QApplication.translate("tilauscope_beancave", "Withdrawing it later removes it from the library, not from the roasters who already imported it."), "body"))
        self.agree = QCheckBox(QApplication.translate("tilauscope_beancave", "Any roaster may use this coffee and adapt it."))
        lay.addWidget(self.agree)
        row = QHBoxLayout()
        row.addStretch()
        cancel = card_button(QApplication.translate("Button", "Cancel"))
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        self.publish = card_button(QApplication.translate("tilauscope_beancave", "Publish"), "primary")
        self.publish.setIcon(make_icon(SVG_PROG_UPLOAD, THEME['BG'], QSize(18, 18)))
        self.publish.setEnabled(False)
        self.publish.clicked.connect(self.accept)
        self.agree.toggled.connect(self.publish.setEnabled)
        row.addWidget(self.publish)
        lay.addLayout(row)
        self.setStyleSheet(self.styleSheet() + _QSS)

    @staticmethod
    def _line(path_d: str, colour: str, text: str) -> QHBoxLayout:
        line = QHBoxLayout()
        line.setSpacing(10)
        line.addWidget(_icon_label(path_d, colour, 18))
        line.addWidget(_label(text, css=f"color:{THEME['TEXT']};font-size:14px;", wrap=True), 1)
        return line


def ask_publish(parent: QWidget, name: str, tasting: bool, brewing: bool) -> bool:
    dialog = PublishDialog(parent, name, tasting, brewing)
    return dialog.exec() == PublishDialog.DialogCode.Accepted


# ── the tab ─────────────────────────────────────────────────────────────────

class LibraryTab(QWidget):
    """``host`` is BeanCave: its selected coffee, its roasts, its import, its machine and event colours."""

    def __init__(self, host: Any, library: Library | None = None,
                 signer: Callable[[], Sign | None] = library_identity.signer) -> None:
        super().__init__(host if isinstance(host, QWidget) else None)
        self._host = host
        self._library = library or Library(LIBRARY_URL)
        self._signer = signer
        self._cards: list[Card] = []        # the pages received so far, in the relay's order
        self._rows: dict[str, _Row] = {}
        self._selected = ""
        self._next, self._total = "", 0
        # Each query of the list has its number: a page answering an older one is ignored.
        self._query = 0
        self._query_filters: dict[str, Any] = {}
        self._more = ""                     # the next page: '', 'loading' or 'failed'
        self._started = self._loaded = self._loading = self._closed = False
        self._busy: set[str] = set()
        self._download_dir: Path | None = None
        self._withdrawing = ""
        self._machine_before_mine = False
        # The roast cards met so far: what the package said, and the last few images drawn from it.
        self._card_parts: dict[str, tuple[dict[str, Any], GreenBean, list[float | None]]] = {}
        self._card_images: dict[str, QImage] = {}
        self.setStyleSheet(base_qss(ground=False) + _QSS)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._pages = QStackedWidget()
        outer.addWidget(self._pages)

        # page 0: loading, unreachable, refused — the whole tab
        self._panel, self._panel_title, self._panel_text, self._retry = self._message_panel(with_retry=True)
        self._retry.clicked.connect(self._on_retry)
        holder = QWidget()
        hl = QVBoxLayout(holder)
        hl.setContentsMargins(16, 16, 16, 16)
        hl.addWidget(self._panel)
        self._pages.addWidget(holder)

        # page 1: browse — the list on the left, the selected roast's card on the right
        browse_page = QWidget()
        lib = QHBoxLayout(browse_page)
        lib.setContentsMargins(16, 16, 16, 16)
        lib.setSpacing(16)
        master_host = QWidget()
        master_host.setFixedWidth(300)
        master = QVBoxLayout(master_host)
        master.setContentsMargins(0, 0, 0, 0)
        master.setSpacing(10)
        self.search = QLineEdit()
        self.search.setObjectName("libSearch")
        self.search.setPlaceholderText(QApplication.translate("tilauscope_beancave", "Coffee, country, process…"))
        self.search.setClearButtonEnabled(True)
        self.search.addAction(make_icon(SVG_SEARCH, THEME['SUBTEXT'], QSize(14, 14)), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self._on_search_typed)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(_SEARCH_PAUSE_MS)
        self._search_timer.timeout.connect(self._on_search_settled)
        master.addWidget(self.search)
        filters = QHBoxLayout()
        filters.setSpacing(8)
        self.machine_only = self._chip_button(QApplication.translate("tilauscope_beancave", "My machine"), checkable=True)
        self.machine_only.setChecked(False)   # every machine by default: a filter the operator turns on
        self.machine_only.toggled.connect(self._on_machine_toggled)
        filters.addWidget(self.machine_only)
        self.mine = self._chip_button("", checkable=True)
        self.mine.toggled.connect(self._on_mine_toggled)
        filters.addWidget(self.mine)
        filters.addStretch()
        master.addLayout(filters)
        self._count = _label("", css=f"color:{THEME['OVERLAY0']};font-size:12px;padding:0 4px;")
        master.addWidget(self._count)
        self._list_host = QWidget()
        list_column = QVBoxLayout(self._list_host)
        list_column.setContentsMargins(0, 0, 0, 0)
        self._list = QVBoxLayout()
        self._list.setSpacing(2)
        list_column.addLayout(self._list)
        self._more_line = QPushButton()
        self._more_line.setObjectName("libMore")
        self._more_line.setCursor(Qt.CursorShape.PointingHandCursor)
        self._more_line.clicked.connect(self._on_more_clicked)
        self._more_line.hide()
        list_column.addWidget(self._more_line)
        list_column.addStretch(1)
        self._list_scroll = self._scroll(self._list_host)
        bar = self._list_scroll.verticalScrollBar()
        bar.valueChanged.connect(self._on_list_scrolled)
        bar.rangeChanged.connect(self._on_list_resized)
        # After a page arrives, once its rows are laid out: a list shorter than its view asks for more.
        self._more_check = QTimer(self)
        self._more_check.setSingleShot(True)
        self._more_check.setInterval(0)
        self._more_check.timeout.connect(self._maybe_more)
        master.addWidget(self._list_scroll, 1)
        lib.addWidget(master_host)

        self._detail_stack = QStackedWidget()
        detail_host = QWidget()
        detail = QVBoxLayout(detail_host)
        detail.setContentsMargins(0, 0, 0, 0)
        detail.setSpacing(12)
        self.card_view = _CardView()
        detail.addWidget(self.card_view)
        self._bar_holder = QVBoxLayout()
        self._bar_holder.setContentsMargins(0, 0, 0, 0)
        detail.addLayout(self._bar_holder)
        detail.addStretch(1)
        self._bar: QWidget | None = None
        self._detail_stack.addWidget(detail_host)
        self._nothing, self._nothing_title, self._nothing_text, _ = self._message_panel(with_retry=False)
        self._detail_stack.addWidget(self._nothing)
        lib.addWidget(self._detail_stack, 1)
        self._pages.addWidget(browse_page)

        self._toast = _label("", "libToast")
        self._toast.setParent(self)
        self._toast.hide()
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.setInterval(4000)
        self._toast_timer.timeout.connect(self._toast.hide)
        self._update_mine_count()

    # ── building blocks ─────────────────────────────────────────────────────
    @staticmethod
    def _chip_button(text: str, checkable: bool = False) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("libChipButton")
        button.setCheckable(checkable)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    @staticmethod
    def _scroll(widget: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background:transparent; border:none; }")
        scroll.setWidget(widget)
        return scroll

    @staticmethod
    def _message_panel(with_retry: bool) -> tuple[QFrame, QLabel, QLabel, QPushButton]:
        panel = QFrame()
        panel.setObjectName("libPanel")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(30, 30, 30, 30)
        lay.setSpacing(14)
        lay.addStretch()
        title = _label("", css=f"color:{THEME['TEXT']};font-size:20px;font-weight:700;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text = _label("", css=f"color:{THEME['SUBTEXT']};font-size:15px;", wrap=True)
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text.setMaximumWidth(460)
        lay.addWidget(title)
        # Centred by stretches: an alignment flag would leave the wrapped text one line high.
        centred = QHBoxLayout()
        centred.addStretch()
        centred.addWidget(text, 1)
        centred.addStretch()
        lay.addLayout(centred)
        retry = QPushButton(QApplication.translate("tilauscope_beancave", "Try again"))
        retry.setObjectName("libGhost")
        retry.setCursor(Qt.CursorShape.PointingHandCursor)
        retry.setVisible(with_retry)
        lay.addWidget(retry, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addStretch()
        return panel, title, text, retry

    # ── host ────────────────────────────────────────────────────────────────
    def _qmc(self) -> Any:
        return getattr(getattr(self._host, 'aw', None), 'qmc', None)

    def _this_machine(self) -> str:
        return str(getattr(self._qmc(), 'roastertype_setup', '') or '')

    def _say(self, text: str, icon: QMessageBox.Icon = QMessageBox.Icon.Warning) -> None:
        show_styled_message(self.window(), QApplication.translate("tilauscope_beancave", "Library"), text, icon)

    def _show_toast(self, text: str, stay: bool = False) -> None:
        self._toast.setText(text)
        self._toast.adjustSize()
        self._toast.move((self.width() - self._toast.width()) // 2, self.height() - self._toast.height() - 22)
        self._toast.show()
        self._toast.raise_()
        if stay:
            self._toast_timer.stop()
        else:
            self._toast_timer.start()

    # ── lifetime ────────────────────────────────────────────────────────────
    def on_shown(self) -> None:
        """The first page is fetched the first time the tab is shown; nothing of the library is asked before."""
        try:
            if not self._started:
                self._started = True
                self._refetch()
        except Exception:  # noqa: BLE001  pylint: disable=broad-except — reached from a tab-change slot
            _log.exception("library not fetched")

    def shutdown(self) -> None:
        """BeanCave closes: what is still running finishes unheard, and the window is never shown again."""
        self._closed = True
        self._toast_timer.stop()
        self._search_timer.stop()
        self._more_check.stop()
        for thread in self.findChildren(QThread):
            if thread.isRunning():
                park_until_finished(thread, getattr(thread, '_worker', None))
        if self._download_dir is not None:
            shutil.rmtree(self._download_dir, ignore_errors=True)
            self._download_dir = None

    def _run(self, task: str, call: Callable[[], Any]) -> None:
        thread = QThread(self)
        job = _Job(task, call)
        job.moveToThread(thread)
        thread.started.connect(job.run)
        job.done.connect(self._on_done)
        job.failed.connect(self._on_failed)
        job.done.connect(thread.quit)
        job.failed.connect(thread.quit)
        # Never job.deleteLater: run in the job's own thread, it frees the job under
        # handles still held here and deadlocks on the GIL. The thread takes it along.
        thread._worker = job  # type: ignore[attr-defined]
        thread.finished.connect(thread.deleteLater)
        self._busy.add(task)
        self._sync_busy()
        thread.start()

    def _sync_busy(self) -> None:
        for button in self.findChildren(QPushButton, "libTonal"):
            button.setEnabled("import" not in self._busy)
        for button in self.findChildren(QPushButton, "libGhost"):
            if button is not self._retry:
                button.setEnabled("withdraw" not in self._busy)

    # ── the list ────────────────────────────────────────────────────────────
    def _filters(self) -> dict[str, Any]:
        """What the relay is asked for: Mine is its own view, the machine filter steps aside there."""
        if self.mine.isChecked():
            return {"text": self.search.text(), "ids": tuple(published_ids())}
        return {"text": self.search.text(), "roaster": self._this_machine() if self.machine_only.isChecked() else ""}

    def _refetch(self) -> None:
        """The list again from its first page, for the filters set now; never before the tab was first shown."""
        if not self._started or self._closed:
            return
        self._search_timer.stop()
        self._query += 1
        self._query_filters = self._filters()
        self._more = ""
        if self.mine.isChecked() and not self._query_filters["ids"]:
            self._loading = False                 # nothing published here: nothing to ask
            self._show_page(Page(cards=(), next="", total=0), first=True)
            return
        self._loading = True
        if not self._loaded or self._pages.currentIndex() == 0:
            self._panel_title.setText(QApplication.translate("tilauscope_beancave", "Loading the library…"))
            self._panel_text.setText("")
            self._retry.hide()
            self._pages.setCurrentIndex(0)
        library, filters = self._library, self._query_filters
        self._run(f"{_PAGE}:{self._query}", lambda: library.search(**filters))

    def _load_more(self) -> None:
        self._more = "loading"
        self._sync_more()
        library, filters, cursor = self._library, self._query_filters, self._next
        self._run(f"{_MORE}:{self._query}", lambda: library.search(**filters, cursor=cursor))

    @pyqtSlot()
    def _maybe_more(self) -> None:
        """The next page once the list is scrolled near its end, or when it does not fill its view."""
        if not self._next or self._more or self._loading or self._closed or not self._list_scroll.isVisible():
            return
        # From the rows' own height: the scroll bar's range catches up only once the new rows are laid out.
        below = (self._list_host.sizeHint().height() - self._list_scroll.verticalScrollBar().value()
                 - self._list_scroll.viewport().height())
        if below <= _MORE_MARGIN_PX:
            self._load_more()

    @pyqtSlot(int)
    def _on_list_scrolled(self, _value: int) -> None:
        try:
            self._maybe_more()
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _log.exception("library next page not asked")

    @pyqtSlot(int, int)
    def _on_list_resized(self, _low: int, _high: int) -> None:
        try:
            self._maybe_more()
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _log.exception("library next page not asked")

    @pyqtSlot()
    def _on_more_clicked(self) -> None:
        try:
            if self._more == "failed":
                self._load_more()
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _log.exception("library next page not retried")

    def _sync_more(self) -> None:
        if self._more == "loading":
            self._more_line.setText(QApplication.translate("tilauscope_beancave", "Loading more…"))
        elif self._more == "failed":
            self._more_line.setText(QApplication.translate("tilauscope_beancave", "The next roasts did not load. Click to try again."))
        self._more_line.setEnabled(self._more == "failed")
        self._more_line.setVisible(bool(self._more))

    @pyqtSlot()
    def _on_retry(self) -> None:
        try:
            if not self._loading:
                self._refetch()
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _log.exception("library retry failed")

    def _show_unreachable(self, kind: str) -> None:
        if kind == "offline":
            self._panel_title.setText(QApplication.translate("tilauscope_beancave", "The library cannot be reached"))
            self._panel_text.setText(QApplication.translate("tilauscope_beancave", "Check the internet connection. Your own coffees and roasts are not affected."))
        else:
            self._panel_title.setText(QApplication.translate("tilauscope_beancave", "The library is not available"))
            self._panel_text.setText(failure_sentence("list", kind))
        self._retry.show()
        self._pages.setCurrentIndex(0)

    # ── results ─────────────────────────────────────────────────────────────
    @pyqtSlot(str, object)
    def _on_done(self, task: str, result: Any) -> None:
        if self._closed:
            return
        try:
            self._busy.discard(task)
            self._sync_busy()
            kind, _, query = task.partition(":")
            if kind == _CARD:
                self._card_arrived(*result)
            elif kind in (_PAGE, _MORE):
                if int(query) != self._query:
                    return                              # an older query, answered after a newer one
                if kind == _PAGE:
                    self._loading = False
                self._more = ""
                self._show_page(result, first=kind == _PAGE)
            elif task == "import":
                self._toast.hide()
                self._import_downloaded(Path(result))
            elif task == "publish":
                self._published(*result)
            elif task == "withdraw":
                self._withdrawn(str(result))
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _log.exception("library %s result not shown", task)

    @pyqtSlot(str, str)
    def _on_failed(self, task: str, kind: str) -> None:
        if self._closed:
            return
        try:
            self._busy.discard(task)
            self._sync_busy()
            what, _, detail = task.partition(":")
            if what == _CARD:                         # said in the card's place, never in a dialog
                if detail == self._selected:
                    self.card_view.show_message(failure_sentence(_CARD, kind))
                return
            if what in (_PAGE, _MORE):
                if int(detail) != self._query:
                    return
                if what == _PAGE:
                    self._loading = False
                    self._show_unreachable(kind)
                else:                                 # said at the end of the list, never in a dialog
                    self._more = "failed"
                    self._sync_more()
                return
            self._toast.hide()
            if task == "import" and self._download_dir is not None:
                shutil.rmtree(self._download_dir, ignore_errors=True)
                self._download_dir = None
            if task == "withdraw" and kind == "unknown":
                self._withdrawn(self._withdrawing)     # already gone from the library: nothing left to withdraw
                return
            self._say(failure_sentence(task, kind))
            if task == "import" and kind == "unknown":
                self._refetch()
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _log.exception("library %s failure not shown", task)

    # ── browsing ────────────────────────────────────────────────────────────
    def _clear_rows(self) -> None:
        for row in self._rows.values():
            self._list.removeWidget(row)
            row.hide()
            row.deleteLater()
        self._rows = {}
        self._cards = []

    def _show_page(self, page: Page, first: bool) -> None:
        """The first page replaces the list; the next ones are added at its end."""
        if first:
            self._clear_rows()
        self._loaded = True
        self._next, self._total = page.next, page.total
        mine = set(published_ids())
        for card in page.cards:
            if card.id and card.id not in self._rows:
                row = _Row(card, card.id in mine)
                row.setParent(self._list_host)
                row.clicked.connect(self._on_card_clicked)
                self._list.addWidget(row)
                row.show()
                self._rows[card.id] = row
                self._cards.append(card)
        self._pages.setCurrentIndex(1)
        self._refresh()
        self._more_check.start()

    def visible_cards(self) -> list[Card]:
        return list(self._cards)

    def _update_mine_count(self) -> None:
        self.mine.setText(QApplication.translate("tilauscope_beancave", "Mine · {0}").format(len(published_ids())))

    def _refresh(self) -> None:
        self._update_mine_count()
        self._count.setText(QApplication.translate("tilauscope_beancave", "1 roast · newest first") if self._total == 1 else
                            QApplication.translate("tilauscope_beancave", "{0} roasts · newest first").format(self._total))
        self._sync_more()
        if not self._cards:
            self._explain_nothing()
            self._detail_stack.setCurrentIndex(1)
            self._select("")
            return
        self._detail_stack.setCurrentIndex(0)
        self._select(self._selected if self._selected in self._rows else self._cards[0].id)

    def _explain_nothing(self) -> None:
        text = self.search.text().strip()
        if self.mine.isChecked() and not text:
            self._nothing_title.setText(QApplication.translate("tilauscope_beancave", "You have not published a roast yet"))
            self._nothing_text.setText(QApplication.translate("tilauscope_beancave", "Open a roast in the Roasts tab, then Export › Publish to the library."))
        elif not text and not self.mine.isChecked() and not self.machine_only.isChecked():
            self._nothing_title.setText(QApplication.translate("tilauscope_beancave", "No roast in the library yet"))
            self._nothing_text.setText(QApplication.translate("tilauscope_beancave", "Be the first: open a roast in the Roasts tab, then Export › Publish to the library."))
        else:
            self._nothing_title.setText(QApplication.translate("tilauscope_beancave", "No coffee matches"))
            self._nothing_text.setText(QApplication.translate("tilauscope_beancave", "Clear the search, or turn off My machine."))

    @pyqtSlot(str)
    def _on_search_typed(self, _text: str = "") -> None:
        """Sent to the relay once the typing pauses, not at every key."""
        try:
            if self._started:
                self._search_timer.start()
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _log.exception("library search not scheduled")

    @pyqtSlot()
    def _on_search_settled(self) -> None:
        try:
            self._refetch()
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _log.exception("library search failed")

    @pyqtSlot(bool)
    def _on_machine_toggled(self, on: bool) -> None:
        try:
            if on and self.mine.isChecked():
                self.mine.blockSignals(True)
                self.mine.setChecked(False)
                self.mine.blockSignals(False)
            self._refetch()
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _log.exception("library machine filter failed")

    @pyqtSlot(bool)
    def _on_mine_toggled(self, on: bool) -> None:
        """Mine is its own view: the machine filter steps aside, and comes back as it was."""
        try:
            self.machine_only.blockSignals(True)
            if on:
                self._machine_before_mine = self.machine_only.isChecked()
                self.machine_only.setChecked(False)
            else:
                self.machine_only.setChecked(self._machine_before_mine)
            self.machine_only.blockSignals(False)
            self._refetch()
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _log.exception("library mine filter failed")

    @pyqtSlot(str)
    def _on_card_clicked(self, coffee_id: str) -> None:
        try:
            self._select(coffee_id)
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _log.exception("library selection failed")

    def selected_card(self) -> Card | None:
        return next((c for c in self._cards if c.id == self._selected), None)

    def _select(self, coffee_id: str) -> None:
        self._selected = coffee_id
        for cid, row in self._rows.items():
            row.set_selected(cid == coffee_id)
        card = self.selected_card()
        self._show_detail(card)
        if card is not None:
            self._show_card(card.id)

    # ── the roast card ──────────────────────────────────────────────────────
    def _show_card(self, coffee_id: str) -> None:
        """The card from what is kept, or its package fetched: selecting a roast again after a failure retries."""
        image = self._card_images.get(coffee_id)
        if image is None and coffee_id in self._card_parts:
            image = self._draw_card(coffee_id)
        if image is not None:
            self.card_view.show_image(image)
            return
        self.card_view.show_message(QApplication.translate("tilauscope_beancave", "Loading the roast card…"))
        task = f"{_CARD}:{coffee_id}"
        if task in self._busy:
            return
        from tilauscope.backup import app_version  # noqa: PLC0415
        version, build = app_version()
        library = self._library
        self._run(task, lambda: _load_card(library, coffee_id, version, build))

    def _card_arrived(self, coffee_id: str, roast: dict[str, Any], bean: GreenBean, ror: list[float | None]) -> None:
        """Kept whatever is selected now; drawn and shown only when it is still the selected roast."""
        self._card_parts[coffee_id] = (roast, bean, ror)
        if coffee_id != self._selected:
            return
        image = self._draw_card(coffee_id)
        if image is None:
            self.card_view.show_message(failure_sentence(_CARD, "local"))
        else:
            self.card_view.show_image(image)

    def _draw_card(self, coffee_id: str) -> QImage | None:
        """The same image as Roasts › Export › Roast card; on the GUI thread only."""
        from tilauscope.beancave_roast_card import RoastSocialCard  # noqa: PLC0415
        roast, bean, ror = self._card_parts[coffee_id]
        colours = getattr(self._qmc(), 'EvalueColor', None)
        try:
            image = RoastSocialCard().render(roast, bean=bean, deltabt=ror, ror_unit=str(roast.get('mode') or 'C'),
                                             lane_colors=list(colours) if colours else None)
        except Exception:  # noqa: BLE001  pylint: disable=broad-except — a roast from elsewhere
            _log.exception("library roast card not drawn")
            return None
        while len(self._card_images) >= _IMAGES_KEPT:
            del self._card_images[next(iter(self._card_images))]
        self._card_images[coffee_id] = image
        return image

    def _show_detail(self, card: Card | None) -> None:
        """The bar under the card: their tasting and Import, or yours and Withdraw."""
        if self._bar is not None:
            self._bar_holder.removeWidget(self._bar)
            self._bar.hide()
            self._bar.deleteLater()
            self._bar = None
        if card is None:
            return
        mine = card.id in published_ids()
        self._bar = QWidget()
        column = QVBoxLayout(self._bar)
        column.setContentsMargins(4, 0, 0, 0)
        column.setSpacing(10)
        bar = QHBoxLayout()
        bar.setSpacing(16)
        said = QVBoxLayout()
        said.setSpacing(6)
        if mine:
            said.addWidget(_label(QApplication.translate("tilauscope_beancave", "YOUR ROAST"), "libEyebrow"))
            if card.published:
                when = QLocale().toString(QDate.fromString(card.published, Qt.DateFormat.ISODate), "d MMM")
                text = QApplication.translate("tilauscope_beancave", "Published {0} · other roasters can import it now.").format(when)
            else:
                text = QApplication.translate("tilauscope_beancave", "Other roasters can import it now.")
            said.addWidget(_label(text, css=f"color:{THEME['TEXT']};font-size:14px;", wrap=True))
        else:
            said.addWidget(_label(QApplication.translate("tilauscope_beancave", "THEIR TASTING"), "libEyebrow"))
            verdict = verdict_sentence(card.verdict)
            said.addWidget(_label(verdict or QApplication.translate("tilauscope_beancave", "Not tasted"),
                                  css=f"color:{THEME['TEXT'] if verdict else THEME['OVERLAY0']};font-size:14px;", wrap=True))
            if card.flavours:
                chips_host = QWidget()
                chips = FlowLayout(chips_host, margin=0, spacing=6)
                for flavour in card.flavours:
                    chips.addWidget(_label(flavour, "libChip"))
                said.addWidget(chips_host)
        bar.addLayout(said, 1)
        if mine:
            action = QPushButton(QApplication.translate("tilauscope_beancave", "Withdraw from the library"))
            action.setObjectName("libGhost")
            action.clicked.connect(self._on_withdraw_clicked)
        else:
            action = QPushButton(QApplication.translate("tilauscope_beancave", "Import this coffee"))
            action.setObjectName("libTonal")
            action.setIcon(make_icon(SVG_PROG_DOWNLOAD, THEME['ACCENT'], QSize(22, 22)))
            action.setIconSize(QSize(22, 22))
            action.clicked.connect(self._on_import_clicked)
        action.setCursor(Qt.CursorShape.PointingHandCursor)
        bar.addWidget(action, 0, Qt.AlignmentFlag.AlignVCenter)
        column.addLayout(bar)
        if not mine and card.roaster:
            column.addLayout(self._machine_line(card.roaster))   # another machine: a curve to read, not to copy
        self._bar_holder.addWidget(self._bar)
        self._sync_busy()

    def _machine_line(self, roaster: str) -> QHBoxLayout:
        from tilauscope.coffee_share import other_machine  # noqa: PLC0415
        here, name = self._this_machine(), canonical_roaster_name(roaster)
        other = other_machine(roaster, here)
        if other:
            text, colour = QApplication.translate("tilauscope_beancave", "Roasted on a {0}. Use it as a curve to read, not to copy.").format(other), THEME['YELLOW']
        elif here:
            text, colour = QApplication.translate("tilauscope_beancave", "Roasted on a {0}, like yours").format(name), THEME['SUBTEXT']
        else:
            text, colour = QApplication.translate("tilauscope_beancave", "Roasted on a {0}").format(name), THEME['SUBTEXT']
        line = QHBoxLayout()
        line.setSpacing(10)
        line.addWidget(_icon_label(_SVG_MACHINE, colour, 20))
        line.addWidget(_label(text, css=f"color:{colour};font-size:14px;", wrap=True), 1)
        return line

    # ── import ──────────────────────────────────────────────────────────────
    @pyqtSlot()
    def _on_import_clicked(self) -> None:
        try:
            card = self.selected_card()
            if card is None or "import" in self._busy:
                return
            self._download_dir = Path(tempfile.mkdtemp(prefix="tilau-library-"))
            folder, library = self._download_dir, self._library
            self._show_toast(QApplication.translate("tilauscope_beancave", "Downloading {0}…").format(card.name), stay=True)
            self._run("import", lambda: library.download(card.id, folder))
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _log.exception("library import not started")

    def _import_downloaded(self, path: Path) -> None:
        """The existing import, preview included; the downloaded file goes once it has been read."""
        try:
            self._host.on_import_coffee(False, str(path))
        finally:
            if self._download_dir is not None:
                shutil.rmtree(self._download_dir, ignore_errors=True)
                self._download_dir = None

    # ── publish ─────────────────────────────────────────────────────────────
    def publish_roast(self, bean: Any, path: Path | None) -> bool:
        """Roasts › Export › Publish to the library: this roast, with its coffee. True once it is being sent."""
        try:
            return self._publish(bean, path)
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _log.exception("library publish not started")
            self._say(failure_sentence("publish", "local"))
            return False

    def _publish(self, bean: Any, path: Path | None) -> bool:
        if "publish" in self._busy or path is None:
            return False
        from tilauscope.coffee_share import gather, save  # noqa: PLC0415
        roast = core.read_alog(path)
        if roast.get("tilau_shared"):
            self._say(QApplication.translate("tilauscope_beancave", "This roast was shared by another roaster: it is theirs to publish."),
                      QMessageBox.Icon.Information)
            return False
        source = gather(bean, self._host._metadata_cache.records.values(), self._host.beancave_directory) if bean else None  # noqa: SLF001
        held = next((r for r in source.roasts if Path(r.filepath_str) == Path(path)), None) if source else None
        if held is None:
            self._say(QApplication.translate("tilauscope_beancave", "Only a real roast of a coffee of your BeanCave can be published: the library lists a roast under its coffee."),
                      QMessageBox.Icon.Information)
            return False
        sign = self._signer()
        if sign is None:
            self._say(QApplication.translate("tilauscope_beancave", "Publishing needs the system keychain, which does not answer on this computer. Browsing and importing coffees still work."))
            return False
        source = replace(source, reference=held)       # the roast on screen, starred or not
        tasting = next(iter(source.tastings_for(core.SHARE).values()), None)
        try:
            card = card_from(bean, roast, tasting)
        except ValueError:
            self._say(QApplication.translate("tilauscope_beancave", "This roast has no CHARGE or no DROP marked, so the library cannot show its curve."))
            return False
        if not ask_publish(self.window(), bean.name, tasting is not None, bool(bean.dial_ins)):
            return False
        library = self._library

        def send() -> tuple[Card, str]:
            with tempfile.TemporaryDirectory(prefix="tilau-library-") as folder:
                target = Path(folder) / f"coffee{core.EXTENSION}"
                save(target, core.SHARE, source, card)
                return card, library.publish(target.read_bytes(), sign)

        self._show_toast(QApplication.translate("tilauscope_beancave", "Publishing {0}…").format(bean.name), stay=True)
        self._run("publish", send)
        return True

    def _published(self, card: Card, coffee_id: str) -> None:
        """Mine shows it, fetched again from the relay (only once the tab has been shown)."""
        ids = published_ids()
        if coffee_id not in ids:
            _set_published([*ids, coffee_id])
        self._selected = coffee_id
        if self.mine.isChecked():
            self._refetch()
        else:
            self.mine.setChecked(True)          # its toggle fetches the list again
        self._update_mine_count()
        self._show_toast(QApplication.translate("tilauscope_beancave", "Published: {0}").format(card.name))

    # ── withdraw ────────────────────────────────────────────────────────────
    @pyqtSlot()
    def _on_withdraw_clicked(self) -> None:
        try:
            card = self.selected_card()
            if card is None or "withdraw" in self._busy:
                return
            answer = show_styled_message(
                self.window(), QApplication.translate("tilauscope_beancave", "Withdraw from the library"),
                QApplication.translate("tilauscope_beancave", "Withdraw {0} from the library? Roasters who already imported it keep their copy.").format(card.name),
                QMessageBox.Icon.Question,
                buttons=[QApplication.translate("tilauscope_beancave", "Withdraw"), QApplication.translate("Button", "Cancel")])
            if answer != 0:
                return
            sign = self._signer()
            if sign is None:
                self._say(QApplication.translate("tilauscope_beancave", "Withdrawing needs the system keychain, which does not answer on this computer. Try again once it does."))
                return
            library, self._withdrawing = self._library, card.id

            def withdraw() -> str:
                library.withdraw(card.id, sign)
                return card.id

            self._run("withdraw", withdraw)
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _log.exception("library withdraw not started")

    def _withdrawn(self, coffee_id: str) -> None:
        """Gone from the list at once, then the list and its count fetched again."""
        card = next((c for c in self._cards if c.id == coffee_id), None)
        _set_published([i for i in published_ids() if i != coffee_id])
        row = self._rows.pop(coffee_id, None)
        if row is not None:
            self._list.removeWidget(row)
            row.hide()
            row.deleteLater()
            self._cards = [c for c in self._cards if c.id != coffee_id]
            self._total = max(0, self._total - 1)
        self._refresh()
        self._refetch()
        if card is not None:
            self._show_toast(QApplication.translate("tilauscope_beancave", "Withdrawn: {0}").format(card.name))

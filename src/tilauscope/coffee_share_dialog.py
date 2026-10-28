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

"""BeanCave › Share & print › Share this coffee: one coffee in one file, for another roaster or another computer."""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import QDateTime, QLocale, QStandardPaths, Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (QApplication, QCheckBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QMessageBox,
                             QVBoxLayout, QWidget)

from tilaucore import coffee_share as core
from tilauscope import coffee_share
from tilauscope.tilauscope_types import THEME, show_styled_message
from tilauscope.widgets.card_dialog import CardDialog, card_button, card_label
from tilauscope.widgets.controls import SegmentedControl

_log = logging.getLogger(__name__)

_MODES = (core.SHARE, core.MOVE)


def _row(mark: str, colour: str, name: str, detail: str) -> QWidget:
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 8, 0, 8)
    lay.setSpacing(12)
    glyph = QLabel(mark)
    glyph.setFixedWidth(18)
    glyph.setStyleSheet(f"color:{colour}; font-weight:700;")
    lay.addWidget(glyph)
    lay.addWidget(QLabel(name), 1)
    caption = card_label(detail, variant="caption")
    caption.setWordWrap(False)
    lay.addWidget(caption)
    return row


def _contents(rows: list[QWidget]) -> QFrame:
    box = QFrame()
    box.setObjectName("tile")
    lay = QVBoxLayout(box)
    lay.setContentsMargins(16, 4, 16, 4)
    lay.setSpacing(0)
    for row in rows:
        lay.addWidget(row)
    return box


def _roast_detail(record) -> str:
    when = QLocale().toString(QDateTime.fromSecsSinceEpoch(int(record.roastepoch or record.mtime)).date(),
                              QLocale.FormatType.ShortFormat)
    return f"{when} · {round(record.weight_in_g)} g" if record.weight_in_g else when


class ShareCoffeeDialog(CardDialog):

    def __init__(self, parent: QWidget | None, source: coffee_share.ShareSource) -> None:
        super().__init__(parent, QApplication.translate("tilauscope_beancave", "Share this coffee"))
        self._source = source
        bean = source.bean
        lay = self.page()
        lay.addWidget(card_label(bean.name, variant="title"))
        facts = " · ".join(str(f) for f in (bean.country, bean.farm, bean.varieties,
                                               f"{bean.altitude} m" if bean.altitude else "") if f)
        if facts:
            lay.addWidget(card_label(facts, variant="caption"))

        self._mode = SegmentedControl([QApplication.translate("tilauscope_beancave", "With another roaster"),
                                       QApplication.translate("tilauscope_beancave", "To another of my computers")])
        self._mode.set_current(0)
        self._mode.changed.connect(self._show_mode)
        lay.addWidget(self._mode)

        self._panes = [self._share_pane(), self._move_pane()]
        for pane in self._panes:
            lay.addWidget(pane)
        lay.addStretch()

        row = QHBoxLayout()
        row.addStretch()
        cancel = card_button(QApplication.translate("Button", "Cancel"))
        cancel.clicked.connect(self.close)
        row.addWidget(cancel)
        save = card_button(QApplication.translate("tilauscope_beancave", "Save package…"), "primary")
        save.clicked.connect(self._save)
        row.addWidget(save)
        lay.addLayout(row)
        self._show_mode(0)

    def _pane(self, intro: str, rows: list[QWidget], note: str) -> QWidget:
        pane = QWidget()
        lay = QVBoxLayout(pane)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        lay.addWidget(card_label(intro, "body"))
        lay.addWidget(card_label(QApplication.translate("tilauscope_beancave", "IN THE PACKAGE"), variant="eyebrow"))
        lay.addWidget(_contents(rows))
        notice = QFrame()
        notice.setObjectName("status")
        inner = QHBoxLayout(notice)
        inner.setContentsMargins(12, 10, 12, 10)
        inner.addWidget(card_label(note, "body"))
        lay.addWidget(notice)
        return pane

    def _share_pane(self) -> QWidget:
        source, ok = self._source, THEME['SUCCESS']
        rows = [_row("✓", ok, QApplication.translate("tilauscope_beancave", "The coffee's record"),
                     QApplication.translate("tilauscope_beancave", "without stock, bags or price"))]
        if source.reference is not None:
            rows.append(_row("★", THEME['YELLOW'], QApplication.translate("tilauscope_beancave", "Reference roast"),
                             _roast_detail(source.reference)))
            tasting = source.tastings_for(core.SHARE)
            if tasting:
                from tilauscope.cave.tasting_dialog import verdict_labels  # noqa: PLC0415
                verdict = verdict_labels().get(next(iter(tasting.values())).verdict, "")
                rows.append(_row("✓", ok, QApplication.translate("tilauscope_beancave", "Its tasting"), verdict))
        else:
            rows.append(_row("☆", THEME['WARNING'], QApplication.translate("tilauscope_beancave", "No reference roast"),
                             QApplication.translate("tilauscope_beancave", "mark the roast you would roast again with a ★ to share it")))
        rows.append(self._brewing_row())
        return self._pane(
            QApplication.translate("tilauscope_beancave", "A starting point for someone roasting the same coffee. Their roast plan does not learn from it: they get a curve to read and to replay."),
            rows,
            QApplication.translate("tilauscope_beancave", "Left out of the roast: your name and organisation, the room's temperature, humidity and pressure, and every folder path, computer name or identifier Artisan wrote into the file."))

    def _move_pane(self) -> QWidget:
        source, ok = self._source, THEME['SUCCESS']
        roasts = str(len(source.roasts))
        if source.reference is not None:
            roasts += " · " + QApplication.translate("tilauscope_beancave", "reference ★ included")
        rows = [_row("✓", ok, QApplication.translate("tilauscope_beancave", "The coffee's record"),
                     QApplication.translate("tilauscope_beancave", "with stock, bags and price")),
                _row("✓", ok, QApplication.translate("tilauscope_beancave", "Roasts"), roasts),
                _row("✓", ok, QApplication.translate("tilauscope_beancave", "Tastings"),
                     str(len(source.tastings_for(core.MOVE)))),
                _row("✓", ok, QApplication.translate("tilauscope_beancave", "Brewing settings and journal"),
                     QApplication.translate("tilauscope_beancave", "{0} · {1} brews").format(
                         len(source.bean.dial_ins), len(source.brews)))]
        return self._pane(
            QApplication.translate("tilauscope_beancave", "Everything about this coffee, as it is here. On the other computer its roasts count as yours: the plan learns from them."),
            rows,
            QApplication.translate("tilauscope_beancave", "Nothing is removed. Nothing is deleted here: the coffee stays on this computer too."))

    def _brewing_row(self) -> QWidget:
        methods = ", ".join(d.method_id for d in self._source.bean.dial_ins if d.method_id)
        return _row("✓", THEME['SUCCESS'], QApplication.translate("tilauscope_beancave", "Brewing settings"),
                    methods or QApplication.translate("tilauscope_beancave", "none yet"))

    def _show_mode(self, index: int) -> None:
        for i, pane in enumerate(self._panes):
            pane.setVisible(i == index)
        if self.isVisible():
            self.fit()

    def _save(self) -> None:
        mode = _MODES[max(0, self._mode.current())]
        folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation) or str(Path.home())
        name = "".join(c if c.isalnum() or c in " -_" else "_" for c in self._source.bean.name).strip() or "coffee"
        chosen, _ = QFileDialog.getSaveFileName(
            self, self.windowTitle(), str(Path(folder) / f"{name}{core.EXTENSION}"),
            QApplication.translate("tilauscope_beancave", "TilauScope coffee") + f" (*{core.EXTENSION})")
        if not chosen:
            return
        target = Path(chosen if chosen.endswith(core.EXTENSION) else chosen + core.EXTENSION)
        try:
            coffee_share.save(target, mode, self._source)
        except Exception:  # pylint: disable=broad-except
            _log.exception("coffee package not written")
            show_styled_message(self, self.windowTitle(), QApplication.translate("tilauscope_beancave", "The package could not be written. Check that the folder exists and that there is free space."), QMessageBox.Icon.Warning)
            return
        self.close()
        buttons = [QApplication.translate("tilauscope_beancave", "Done"),
                   QApplication.translate("tilauscope_beancave", "Show in folder")]
        if show_styled_message(self.parentWidget(), self.windowTitle(),
                               QApplication.translate("tilauscope_beancave", "Package saved: {0}").format(target.name),
                               buttons=buttons) == 1:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target.parent)))


def open_share_coffee(parent: QWidget, source: coffee_share.ShareSource) -> None:
    dialog = ShareCoffeeDialog(parent, source)
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    dialog.exec()


# ── import ──────────────────────────────────────────────────────────────────

class ImportCoffeeDialog(CardDialog):
    """What a package brings, and what it will not touch, before anything is written."""

    def __init__(self, parent: QWidget | None, package: core.Package, plan: coffee_share.ImportPreview) -> None:
        super().__init__(parent, QApplication.translate("tilauscope_beancave", "Import coffee"))
        shared = package.mode == core.SHARE
        manifest, ok = package.manifest, THEME['SUCCESS']
        lay = self.page()

        head = QFrame()
        head.setObjectName("tile")
        inner = QVBoxLayout(head)
        inner.setContentsMargins(16, 12, 16, 12)
        inner.addWidget(card_label(package.bean.name, variant="title"))
        stamp = QDateTime.fromString(str(manifest.get("created", "")), Qt.DateFormat.ISODate)
        when = QLocale().toString(stamp.date(), QLocale.FormatType.ShortFormat) if stamp.isValid() else ""
        origin = (QApplication.translate("tilauscope_beancave", "Shared by another roaster · {0} · TilauScope {1}") if shared
                  else QApplication.translate("tilauscope_beancave", "From another of your computers · {0} · TilauScope {1}"))
        inner.addWidget(card_label(origin.format(when, manifest.get("version", "")), variant="caption"))
        lay.addWidget(head)

        lay.addWidget(card_label(QApplication.translate("tilauscope_beancave", "WHAT YOU GET"), variant="eyebrow"))
        methods = ", ".join(d.method_id for d in package.bean.dial_ins if d.method_id) or \
            QApplication.translate("tilauscope_beancave", "none")
        if shared:
            rows = []
            for roast in package.roasts.values():
                weight = (roast.get("weight") or [0])[0]
                rows.append(_row("★", THEME['YELLOW'], QApplication.translate("tilauscope_beancave", "Their reference roast"),
                                 f"{round(float(weight))} {roast.get('weight', [0, 0, 'g'])[2]}" if weight else ""))
            if not package.roasts:
                rows.append(_row("☆", THEME['SUBTEXT'], QApplication.translate("tilauscope_beancave", "No roast in this package"), ""))
            if package.tastings:
                from tilauscope.cave.tasting_dialog import verdict_labels  # noqa: PLC0415
                verdict = verdict_labels().get(next(iter(package.tastings.values())).verdict, "")
                rows.append(_row("✓", ok, QApplication.translate("tilauscope_beancave", "Their tasting of it"), verdict))
            rows.append(_row("✓", ok, QApplication.translate("tilauscope_beancave", "Their brewing settings"), methods))
        else:
            rows = [_row("✓", ok, QApplication.translate("tilauscope_beancave", "The coffee's record"), ""),
                    _row("✓", ok, QApplication.translate("tilauscope_beancave", "Roasts"),
                         QApplication.translate("tilauscope_beancave", "{0} · {1} new").format(
                             len(package.roasts), len(plan.new_roasts))),
                    _row("✓", ok, QApplication.translate("tilauscope_beancave", "Tastings"), str(len(package.tastings))),
                    _row("✓", ok, QApplication.translate("tilauscope_beancave", "Brewing settings and journal"),
                         QApplication.translate("tilauscope_beancave", "{0} · {1} brews").format(
                             len(package.bean.dial_ins), len(package.brews)))]
        lay.addWidget(_contents(rows))

        self.replace_record = None
        if plan.existing is not None:
            text = (QApplication.translate("tilauscope_beancave", "This coffee is already in your BeanCave. Your record stays as it is; their roast joins it as a shared roast.") if shared
                    else QApplication.translate("tilauscope_beancave", "This coffee is already in your BeanCave. The roasts you do not have yet are added; nothing is deleted or overwritten."))
            lay.addWidget(self._notice("status", "ⓘ  " + text))
            if not shared:
                self.replace_record = QCheckBox(QApplication.translate("tilauscope_beancave", "Replace my record of this coffee"))
                lay.addWidget(self.replace_record)
        if package.roasts and not plan.new_roasts:
            lay.addWidget(self._notice("status", "ⓘ  " + QApplication.translate("tilauscope_beancave", "You already have every roast in this package.")))
        if plan.other_machine:
            lay.addWidget(self._notice("warn", "⚠  " + QApplication.translate("tilauscope_beancave", "Roasted on a {0}. Use it as a curve to read, not to copy.").format(plan.other_machine)))
        if shared:
            lay.addWidget(card_label(QApplication.translate("tilauscope_beancave", "A shared roast is a background curve and a Replay. Your roast plan keeps learning from your own roasts only."), variant="caption"))
        lay.addStretch()

        row = QHBoxLayout()
        row.addStretch()
        cancel = card_button(QApplication.translate("Button", "Cancel"))
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        go = card_button(QApplication.translate("tilauscope_beancave", "Import"), "primary")
        go.clicked.connect(self.accept)
        row.addWidget(go)
        # Coffee and every roast already here: only replacing the record would change anything.
        if plan.existing is not None and not plan.new_roasts:
            go.setEnabled(self.replace_record is not None and self.replace_record.isChecked())
            if self.replace_record is not None:
                self.replace_record.toggled.connect(go.setEnabled)
        self.import_button = go
        lay.addLayout(row)

    @staticmethod
    def _notice(name: str, text: str) -> QFrame:
        box = QFrame()
        box.setObjectName(name)
        inner = QHBoxLayout(box)
        inner.setContentsMargins(12, 10, 12, 10)
        inner.addWidget(card_label(text, "body"))
        return box


def ask_import(parent: QWidget, package: core.Package, plan: coffee_share.ImportPreview) -> bool | None:
    """None when cancelled, else whether to replace the record already here."""
    dialog = ImportCoffeeDialog(parent, package, plan)
    if dialog.exec() != ImportCoffeeDialog.DialogCode.Accepted:
        return None
    return bool(dialog.replace_record is not None and dialog.replace_record.isChecked())

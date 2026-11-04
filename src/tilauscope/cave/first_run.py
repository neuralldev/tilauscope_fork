# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2025-2026 Tilau
# This file is part of TilauScope.

"""BeanCave alone, first launch: where Artisan saves roasts, where the coffees live,
and which roaster the plans are built for.

One question per page, each answer proposed: the roasts folder from the
operator's Artisan settings, the library from that same folder when one is there,
the machine from the name Artisan gives it when TilauScope knows that name.
Nothing is written before the last page is confirmed.
"""

from __future__ import annotations

import json
from pathlib import Path

from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtWidgets import (QApplication, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QPushButton,
                             QStackedWidget, QVBoxLayout, QWidget)

from tilauscope.theme_qss import style_combo_popup
from tilauscope.tilauscope_types import THEME

#: The settings BeanCave reads its two folders and its machine from (the machine as TilauScope names it).
ROASTS_KEY, LIBRARY_KEY, ROASTER_KEY = 'alogDirectory', 'beancaveDirectory', 'tilauscoperoaster'
#: Pages of the first launch.
_PAGES = 3


def needs_first_run(settings: QSettings) -> bool:
    return not (settings.value(ROASTS_KEY, '', str) and settings.value(LIBRARY_KEY, '', str))


def _roast_count(folder: str) -> int:
    return sum(1 for _ in Path(folder).glob('*.alog')) if folder and Path(folder).is_dir() else 0


def _coffee_count(folder: str) -> int | None:
    """Coffees of the library in `folder`, None when there is none."""
    path = Path(folder) / 'beancave.json' if folder else None
    if path is None or not path.is_file():
        return None
    try:
        return len(json.loads(path.read_text(encoding='utf-8-sig')).get('green_beans', []))
    except (OSError, ValueError, AttributeError):
        return None


def _page_head(page: QVBoxLayout, step: int, title: str, detail: str) -> None:
    """The progress dashes, the question and what the answer is for."""
    dots = QHBoxLayout()
    dots.setSpacing(8)
    for i in range(_PAGES):
        dot = QLabel()
        dot.setFixedSize(32, 4)
        dot.setStyleSheet(f"background:{THEME['ACCENT'] if i < step else THEME['SURFACE1']};border-radius:2px;")
        dots.addWidget(dot)
    dots.addStretch(1)
    page.addLayout(dots)
    heading = QLabel(title)
    heading.setStyleSheet(f"color:{THEME['TEXT']};font-size:24px;font-weight:700;")
    heading.setWordWrap(True)
    page.addWidget(heading)
    explain = QLabel(detail)
    explain.setStyleSheet(f"color:{THEME['SUBTEXT']};font-size:14px;")
    explain.setWordWrap(True)
    page.addWidget(explain)


class _FolderPage(QWidget):
    """One question: a folder, proposed, changeable."""

    def __init__(self, step: int, title: str, detail: str, folder: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.folder = folder
        page = QVBoxLayout(self)
        page.setContentsMargins(0, 0, 0, 0)
        page.setSpacing(18)
        _page_head(page, step, title, detail)
        row = QHBoxLayout()
        self.path = QLabel()
        self.path.setStyleSheet(f"color:{THEME['TEXT']};border:1px solid {THEME['ACCENT']};border-radius:10px;"
                                "padding:10px 14px;font-family:Menlo,Consolas,monospace;")
        self.path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row.addWidget(self.path, 1)
        change = QPushButton(QApplication.translate("tilauscope_beancave", "Change…"))
        change.setCursor(Qt.CursorShape.PointingHandCursor)
        change.clicked.connect(self._choose)
        row.addWidget(change)
        page.addLayout(row)
        self.found = QLabel()
        self.found.setStyleSheet(f"color:{THEME['SUCCESS']};font-size:13px;")
        page.addWidget(self.found)
        page.addStretch(1)
        self._show()

    def _choose(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, '', self.folder or str(Path.home()))
        if folder:
            self.folder = folder
            self._show()

    def found_text(self) -> str:
        return ''

    def _show(self) -> None:
        self.path.setText(self.folder.replace(str(Path.home()), '~', 1) if self.folder else '—')
        self.found.setText(self.found_text())
        owner = self.window()
        if isinstance(owner, FirstRunDialog):
            owner.update_next()


class _RoastsPage(_FolderPage):
    def __init__(self, folder: str, from_artisan: bool, parent: QWidget) -> None:
        self._from_artisan = from_artisan
        super().__init__(1, QApplication.translate("tilauscope_beancave", "Where does Artisan save your roasts?"),
                         QApplication.translate("tilauscope_beancave",
                                                "BeanCave reads your roasts there and takes each new one from your stock."),
                         folder, parent)

    def found_text(self) -> str:
        if not self.folder:
            return ''
        count = QApplication.translate("tilauscope_beancave", "{0} roasts").format(_roast_count(self.folder))
        return (QApplication.translate("tilauscope_beancave", "Found in Artisan's settings · {0}").format(count)
                if self._from_artisan else count)


class _LibraryPage(_FolderPage):
    def __init__(self, folder: str, parent: QWidget) -> None:
        super().__init__(2, QApplication.translate("tilauscope_beancave", "Where should your coffees live?"),
                         QApplication.translate("tilauscope_beancave",
                                                "Your green coffees, sacks and tastings are kept in this folder."),
                         folder, parent)

    def found_text(self) -> str:
        coffees = _coffee_count(self.folder)
        return ('' if coffees is None else
                QApplication.translate("tilauscope_beancave", "A library is already here · {0} coffees").format(coffees))


class _MachinePage(QWidget):
    """The roaster the plans are built for, among the machines TilauScope knows."""

    def __init__(self, machines: list[str], artisan_machine: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.folder = 'machine'   # always answered: « not in the list » is an answer
        page = QVBoxLayout(self)
        page.setContentsMargins(0, 0, 0, 0)
        page.setSpacing(18)
        _page_head(page, 3, QApplication.translate("tilauscope_beancave", "Which roaster do you use?"),
                   QApplication.translate("tilauscope_beancave", "Your roast plans are built for this machine."))
        self.combo = QComboBox()
        self.combo.setMinimumHeight(44)
        style_combo_popup(self.combo)
        for name in machines:
            self.combo.addItem(name, name)
        self.combo.addItem(QApplication.translate("tilauscope_beancave", "Not in the list"), '')
        if artisan_machine in machines:
            self.combo.setCurrentIndex(machines.index(artisan_machine))
        page.addWidget(self.combo)
        note = QLabel(QApplication.translate("tilauscope_beancave", "Not in the list? Plans use a standard machine."))
        note.setStyleSheet(f"color:{THEME['SUBTEXT']};font-size:13px;")
        page.addWidget(note)
        page.addStretch(1)

    def machine(self) -> str:
        return str(self.combo.currentData() or '')


class FirstRunDialog(QDialog):
    """Three pages; the answers are saved on the last one only."""

    def __init__(self, roasts_folder: str, machines: list[str] | None = None, artisan_machine: str = '') -> None:
        super().__init__()
        self.setWindowTitle('BeanCave')
        self.setStyleSheet(f"QDialog {{ background:{THEME['BG']}; }}"
                           f"QPushButton {{ color:{THEME['TEXT']};background:transparent;border:1px solid {THEME['SURFACE1']};"
                           "border-radius:10px;padding:10px 18px;font-size:14px; }"
                           f"QPushButton#firstRunNext {{ background:{THEME['ACCENT']};color:{THEME['BG']};border:none;font-weight:700; }}"
                           f"QPushButton#firstRunNext:disabled {{ background:{THEME['SURFACE1']};color:{THEME['SUBTEXT']}; }}"
                           f"QComboBox {{ color:{THEME['TEXT']};background:{THEME['BG']};border:1px solid {THEME['ACCENT']};"
                           "border-radius:10px;padding:8px 14px;font-size:15px; }")
        self.resize(720, 440)
        body = QVBoxLayout(self)
        body.setContentsMargins(48, 40, 48, 32)
        self.pages = QStackedWidget()
        body.addWidget(self.pages, 1)
        buttons = QHBoxLayout()
        self.back = QPushButton(QApplication.translate("tilauscope_beancave", "Back"))
        self.back.clicked.connect(lambda: self._go(self.pages.currentIndex() - 1))
        buttons.addWidget(self.back)
        buttons.addStretch(1)
        self.next = QPushButton()
        self.next.setObjectName('firstRunNext')
        self.next.clicked.connect(self._next)
        buttons.addWidget(self.next)
        body.addLayout(buttons)
        self.roasts = _RoastsPage(roasts_folder, bool(roasts_folder), self)
        self.library = _LibraryPage(roasts_folder, self)
        self.machine = _MachinePage(list(machines or []), artisan_machine, self)
        for page in (self.roasts, self.library, self.machine):
            self.pages.addWidget(page)
        self._go(0)

    def update_next(self) -> None:
        page = self.pages.currentWidget()
        self.next.setEnabled(bool(page is not None and page.folder))

    def _go(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        self.back.setVisible(index > 0)
        self.next.setText(QApplication.translate("tilauscope_beancave", "Continue") if index < _PAGES - 1
                          else QApplication.translate("tilauscope_beancave", "Open BeanCave"))
        self.update_next()

    def _next(self) -> None:
        index = self.pages.currentIndex()
        if index == 0 and not self.library.folder:
            self.library.folder = self.roasts.folder
            self.library._show()
        if index < _PAGES - 1:
            self._go(index + 1)
            return
        settings = QSettings()
        settings.setValue(ROASTS_KEY, self.roasts.folder)
        settings.setValue(LIBRARY_KEY, self.library.folder)
        settings.setValue(ROASTER_KEY, self.machine.machine())
        self.accept()

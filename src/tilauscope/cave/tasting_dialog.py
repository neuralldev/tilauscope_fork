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

"""Tasting a rested roast, and the one change it asks of the next roast of the same coffee."""

from __future__ import annotations

from datetime import UTC, datetime

from PyQt6.QtCore import QDate, QLocale, Qt
from PyQt6.QtWidgets import (QApplication, QButtonGroup, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                             QPlainTextEdit, QPushButton, QVBoxLayout)

from tilauscope import tasting_log
from tilaucore.tasting_log import DEFECT_WORDS, VERDICT_WORDS
from tilauscope.tilauscope_types import THEME, RoastTasting, show_styled_message
from tilauscope.theme_qss import apply_tilau_theme


def defect_labels() -> dict[str, str]:
    """Defect key → what the operator tastes, in the order of tasting_log.DEFECT_CHANGES."""
    return {key: QApplication.translate(*word) for key, word in DEFECT_WORDS.items()}


def verdict_labels() -> dict[str, str]:
    """Verdict key → its thumb and word, as the operator picked it."""
    return {key: f"{thumb}  {QApplication.translate(*word)}" for key, (thumb, word) in VERDICT_WORDS.items()}


def change_text(defect: str, mode: str = 'C') -> tuple[str, str]:
    """(the change for next time, why) for a defect."""
    return tasting_log.change_text(defect, mode, lambda text: QApplication.translate(*text))


class TastingDialog(QDialog):
    """Would you roast it the same way again, what was off, and what to change next time."""

    def __init__(self, parent, *, directory: str, roast_uuid: str, bean_uuid: str,
                 coffee: str, roast_epoch: int, mode: str = 'C', is_reference: bool = False) -> None:
        super().__init__(parent)
        # frameless translucent window: ground=False, else the grounded base
        # paints the rectangle opaque and squares off the rounded card.
        apply_tilau_theme(self, ground=False)
        self._directory = directory
        self._roast_uuid = roast_uuid
        self._bean_uuid = bean_uuid
        self._mode = mode
        existing = tasting_log.load(directory).entries.get(roast_uuid) or RoastTasting()

        self.setWindowTitle(QApplication.translate("tilauscope_beancave", "Tasting"))
        self.setMinimumWidth(520)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("TastingCard")
        card.setStyleSheet(f"""
            #TastingCard {{ background:{THEME['BG']}; border:2px solid {THEME['ACCENT']};
                            border-radius:14px; }}
            QLabel {{ color:{THEME['TEXT']}; background:transparent; border:none; }}
            QPlainTextEdit {{ background:{THEME['BG']}; color:{THEME['TEXT']}; font-size:12px;
                border:1px solid {THEME['BORDER']}; border-radius:8px; padding:6px 8px; }}
            QPushButton#verdict {{ color:{THEME['SUBTEXT']}; background:transparent;
                border:1px solid {THEME['BORDER']}; border-radius:12px; padding:10px; font-size:13px; }}
            QPushButton#verdict:checked {{ color:{THEME['TEXT']}; border-color:{THEME['SUCCESS']};
                background:rgba(166,227,161,0.10); }}
            QPushButton#reference {{ color:{THEME['OVERLAY1']}; background:transparent;
                border:1px solid {THEME['SURFACE1']}; border-radius:12px; font-size:20px; }}
            QPushButton#reference:checked {{ color:{THEME['YELLOW']}; border-color:{THEME['YELLOW']};
                background:rgba(249,226,175,0.10); }}
            QPushButton#defect {{ color:{THEME['SUBTEXT']}; background:transparent;
                border:1px solid {THEME['BORDER']}; border-radius:14px; padding:6px 12px; font-size:12px; }}
            QPushButton#defect:checked {{ color:{THEME['TODAY']}; border-color:{THEME['TODAY']};
                background:rgba(250,179,135,0.10); }}
            #NextCard {{ border:1px solid {THEME['TODAY']}; border-radius:12px;
                         background:rgba(250,179,135,0.07); }}
        """)
        outer.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(24, 18, 24, 18)
        lay.setSpacing(12)

        roasted = datetime.fromtimestamp(roast_epoch, tz=UTC).astimezone().date() if roast_epoch > 0 else None
        title = QLabel(coffee)
        title.setStyleSheet("font-size:17px;font-weight:700;")
        lay.addWidget(title)
        if roasted is not None:
            # the interface's language, as the roast list: strftime names the day in the process locale
            locale_str = getattr(getattr(getattr(parent, 'aw', None), 'qmc', None), 'locale_str', None)
            locale = QLocale(locale_str) if isinstance(locale_str, str) and locale_str else QLocale()
            day = locale.toString(QDate(roasted.year, roasted.month, roasted.day), 'ddd d MMM')
            sub = QLabel(QApplication.translate("tilauscope_beancave", "Roasted {0} · {1} days of rest").format(
                day, (datetime.now().astimezone().date() - roasted).days))
            sub.setStyleSheet(f"color:{THEME['SUBTEXT']};font-size:12px;")
            lay.addWidget(sub)

        lay.addWidget(self._question(QApplication.translate("tilauscope_beancave", "Would you roast it the same way again?")))
        row = QHBoxLayout()
        self._verdicts = QButtonGroup(self)
        self._verdicts.setExclusive(True)
        for key, text in verdict_labels().items():
            b = QPushButton(text)
            b.setObjectName("verdict")
            b.setCheckable(True)
            b.setProperty('key', key)
            b.setChecked(existing.verdict == key)
            self._verdicts.addButton(b)
            row.addWidget(b)
        self._reference = QPushButton()
        self._reference.setObjectName("reference")
        self._reference.setCheckable(True)
        self._reference.setChecked(is_reference)
        self._is_reference = is_reference
        self._reference.setFixedSize(46, 46)
        self._reference.setCursor(Qt.CursorShape.PointingHandCursor)
        self._reference.toggled.connect(self._refresh_reference)
        row.addWidget(self._reference)
        self._verdicts.buttonToggled.connect(lambda *_: self._refresh_next())
        lay.addLayout(row)

        lay.addWidget(self._question(QApplication.translate("tilauscope_beancave", "What was off?"),
                                     QApplication.translate("tilauscope_common", "optional")))
        chips = QGridLayout()
        chips.setSpacing(8)
        self._defects: dict[str, QPushButton] = {}
        for i, (key, text) in enumerate(defect_labels().items()):
            b = QPushButton(text)
            b.setObjectName("defect")
            b.setCheckable(True)
            b.setChecked(key in existing.defects)
            b.toggled.connect(lambda *_: self._refresh_next())
            self._defects[key] = b
            chips.addWidget(b, i // 3, i % 3)
        lay.addLayout(chips)

        self._notes = QPlainTextEdit(existing.notes)
        self._notes.setPlaceholderText(QApplication.translate("tilauscope_beancave", "Notes — e.g. lovely body, fruit fades fast"))
        self._notes.setMaximumHeight(64)
        lay.addWidget(self._notes)

        self._next = QFrame()
        self._next.setObjectName("NextCard")
        nl = QVBoxLayout(self._next)
        nl.setContentsMargins(14, 10, 14, 10)
        nl.setSpacing(3)
        head = QLabel(QApplication.translate("tilauscope_beancave", "NEXT TIME"))
        head.setStyleSheet(f"color:{THEME['TODAY']};font-size:11px;font-weight:700;letter-spacing:1px;")
        self._next_what = QLabel()
        self._next_what.setWordWrap(True)
        self._next_what.setStyleSheet("font-size:14px;font-weight:600;")
        self._next_why = QLabel()
        self._next_why.setWordWrap(True)
        self._next_why.setStyleSheet(f"color:{THEME['SUBTEXT']};font-size:12px;")
        nl.addWidget(head)
        nl.addWidget(self._next_what)
        nl.addWidget(self._next_why)
        lay.addWidget(self._next)

        nav = QHBoxLayout()
        nav.addStretch(1)
        cancel = QPushButton(QApplication.translate("Button", "Cancel"))
        cancel.clicked.connect(self.reject)
        save = QPushButton("✓ " + QApplication.translate("Message", "Save"))
        save.setStyleSheet(f"QPushButton {{ color:{THEME['SUCCESS']}; border:1px solid {THEME['SUCCESS']};"
                           f"border-radius:8px; padding:6px 16px; background:rgba(166,227,161,0.10); }}")
        save.clicked.connect(self._save)
        nav.addWidget(cancel)
        nav.addWidget(save)
        lay.addLayout(nav)
        self._refresh_next()

    @staticmethod
    def _question(text: str, hint: str = '') -> QLabel:
        q = QLabel(text + (f"  <span style='color:{THEME['OVERLAY0']};font-weight:400;font-size:11px'>{hint}</span>"
                           if hint else ""))
        q.setStyleSheet("font-size:13px;font-weight:600;")
        return q

    def _tasting(self) -> RoastTasting:
        checked = self._verdicts.checkedButton()
        return RoastTasting(
            bean_uuid=self._bean_uuid,
            iso_date=datetime.now().astimezone().date().isoformat(),
            verdict=str(checked.property('key')) if checked is not None else '',
            defects=[k for k, b in self._defects.items() if b.isChecked()],
            notes=self._notes.toPlainText().strip())

    def reference_choice(self) -> bool | None:
        """Whether this roast should be the coffee's reference; None when the star was not offered."""
        return self._reference.isChecked() if not self._reference.isHidden() else None

    def _refresh_reference(self) -> None:
        on = self._reference.isChecked()
        self._reference.setText('★' if on else '☆')
        self._reference.setToolTip(
            QApplication.translate("tilauscope_beancave", "Reference roast — click to remove") if on else
            QApplication.translate("tilauscope_beancave", "Make it the reference roast"))

    def _refresh_next(self) -> None:
        tasting = self._tasting()
        # The star is offered on a Yes, and stays on the reference so it can be
        # removed whatever its verdict; hiding it changes no designation. A roast
        # without a coffee record has nowhere to keep it.
        self._reference.setVisible(bool(self._bean_uuid) and (tasting.verdict == 'yes' or self._is_reference))
        self._refresh_reference()
        change = tasting_log.next_change(tasting)
        if change is not None:
            what, why = change_text(change[0], self._mode)
        elif tasting.verdict == 'yes':
            what, why = (QApplication.translate(*text) for text in tasting_log.NEXT_SAME)
        elif tasting.verdict:
            what, why = (QApplication.translate(*text) for text in tasting_log.NEXT_TICK)
        else:
            self._next.hide()
            return
        self._next_what.setText(what)
        self._next_why.setText(why)
        self._next.show()

    def _save(self) -> None:
        if tasting_log.record(self._directory, self._roast_uuid, self._tasting()):
            self.accept()
        else:
            show_styled_message(self, QApplication.translate("tilauscope_beancave", "Save failed"),
                                QApplication.translate("tilauscope_beancave", "The tasting could not be saved. See the log for details."))

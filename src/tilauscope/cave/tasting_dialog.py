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

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QApplication, QButtonGroup, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                             QPlainTextEdit, QPushButton, QVBoxLayout)

from tilauscope import tasting_log
from tilauscope.tilauscope_types import THEME, RoastTasting, show_styled_message
from tilauscope.theme_qss import apply_tilau_theme


def defect_labels() -> dict[str, str]:
    """Defect key → what the operator tastes, in the order of tasting_log.DEFECT_CHANGES."""
    return {
        'burnt': QApplication.translate("tilauscope_beancave", "Burnt"),
        'bitter': QApplication.translate("tilauscope_beancave", "Bitter, smoky"),
        'flat': QApplication.translate("tilauscope_beancave", "Flat, papery"),
        'bready': QApplication.translate("tilauscope_beancave", "Bready, dull"),
        'grassy': QApplication.translate("tilauscope_beancave", "Grassy, raw"),
        'sour': QApplication.translate("tilauscope_beancave", "Sour, thin"),
    }


def verdict_labels() -> dict[str, str]:
    """Verdict key → its thumb and word, as the operator picked it."""
    return {
        'yes': "👍  " + QApplication.translate("tilauscope_beancave", "Yes"),
        'almost': "🤏  " + QApplication.translate("tilauscope_beancave", "Almost"),
        'no': "👎  " + QApplication.translate("tilauscope_beancave", "No"),
    }


def _degrees(delta_c: float, mode: str) -> str:
    return f"{abs(delta_c) * 1.8:.0f} °F" if mode == 'F' else f"{abs(delta_c):.0f} °C"


def change_text(defect: str, mode: str = 'C') -> tuple[str, str]:
    """(the change for next time, why) for a defect."""
    delta = tasting_log.DEFECT_CHANGES[defect][1]
    texts = {
        'burnt': (QApplication.translate("tilauscope_beancave", "Charge {0} cooler").format(_degrees(delta, mode)),
                  QApplication.translate("tilauscope_beancave", "Burnt usually means the beans met too much heat at the start.")),
        'bitter': (QApplication.translate("tilauscope_beancave", "Burner one notch lower before first crack"),
                   QApplication.translate("tilauscope_beancave", "Bitter, smoky usually means too much heat at the end.")),
        'flat': (QApplication.translate("tilauscope_beancave", "Burner one notch higher before first crack"),
                 QApplication.translate("tilauscope_beancave", "Flat, papery usually means too little heat reaching first crack.")),
        'bready': (QApplication.translate("tilauscope_beancave", "Start with the burner one notch higher"),
                   QApplication.translate("tilauscope_beancave", "Bready, dull usually means the roast dragged for lack of heat.")),
        'grassy': (QApplication.translate("tilauscope_beancave", "Let it develop 20 s longer after first crack"),
                   QApplication.translate("tilauscope_beancave", "Grassy, raw usually means the roast ended too soon after first crack.")),
        'sour': (QApplication.translate("tilauscope_beancave", "Drop {0} later").format(_degrees(delta, mode)),
                 QApplication.translate("tilauscope_beancave", "Sour, thin usually means the beans needed a little more development.")),
    }
    return texts[defect]


class TastingDialog(QDialog):
    """Would you roast it the same way again, what was off, and what to change next time."""

    def __init__(self, parent, *, directory: str, roast_uuid: str, bean_uuid: str,
                 coffee: str, roast_epoch: int, mode: str = 'C') -> None:
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
            sub = QLabel(QApplication.translate("tilauscope_beancave", "Roasted {0} · {1} days of rest").format(
                roasted.strftime("%a %d %b"), (datetime.now().astimezone().date() - roasted).days))
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
        self._verdicts.buttonToggled.connect(lambda *_: self._refresh_next())
        lay.addLayout(row)

        lay.addWidget(self._question(QApplication.translate("tilauscope_beancave", "What was off?"),
                                     QApplication.translate("tilauscope_beancave", "optional")))
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
        cancel = QPushButton(QApplication.translate("tilauscope_beancave", "Cancel"))
        cancel.clicked.connect(self.reject)
        save = QPushButton("✓ " + QApplication.translate("tilauscope_beancave", "Save"))
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

    def _refresh_next(self) -> None:
        tasting = self._tasting()
        change = tasting_log.next_change(tasting)
        if change is not None:
            what, why = change_text(change[0], self._mode)
        elif tasting.verdict == 'yes':
            what, why = (QApplication.translate("tilauscope_beancave", "Nothing to change"),
                         QApplication.translate("tilauscope_beancave", "Roast it the same way next time."))
        elif tasting.verdict:
            what, why = (QApplication.translate("tilauscope_beancave", "Tick what was off"),
                         QApplication.translate("tilauscope_beancave", "It tells the next roast what to change."))
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

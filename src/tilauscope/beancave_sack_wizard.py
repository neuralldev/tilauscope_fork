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

"""New-sack guided assistant for BeanCave: a step-by-step wizard (start, essentials,
sack id, provenance, type & facts, sensory, review) registering an incoming bag of green coffee. Everything sack-related is optional; nothing is written until "Create" on the review page.

Passing ``source_bean`` opens the short new-crop flow instead: the identity of
the coffee is inherited from that record and only what belongs to the new
harvest is asked (year, weight, supplier, and the three lot measurements).
"""

from __future__ import annotations

from tilauscope.theme_qss import apply_tilau_theme

import dataclasses
import logging
import uuid as _uuid
from datetime import datetime
from typing import Final

from PyQt6.QtCore import Qt, QObject, QThread, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from tilauscope.sack_manager import SackLabelsDialog, SackPool
from tilauscope.tilauscope_types import THEME, GreenBean, no_enter_default, show_styled_message

_logd = logging.getLogger('tilaudebug')

_MONO: Final[str] = "'JetBrains Mono', monospace"
_DIM: Final[str] = THEME['OVERLAY0']



# ─────────────────────────────────────────────────────────────────────────────
# Background AI extraction (same CoffeeAIParser as the manual form button)
# ─────────────────────────────────────────────────────────────────────────────

class _WizardAIWorker(QObject):
    """Runs CoffeeAIParser.get_bean_from_url off the UI thread."""

    finished = pyqtSignal(object)   # GreenBean | None
    error = pyqtSignal(str)

    def __init__(self, host, url: str) -> None:
        super().__init__()
        # Capture plain data now — the host widget is never touched off-thread.
        self._ai = host.ai
        self._url = url
        self._categories = list(host.coffee_beans_categories)
        self._methods = dict(host.coffee_processing_methods)
        self._countries = list(host.coffee_producing_countries)
        self._types = dict(host.coffee_bean_types)
        self._species = list(host.coffee_beans_species)

    def run(self) -> None:
        try:
            from tilauscope.bean_extractor import CoffeeAIParser  # noqa: PLC0415
            parser = CoffeeAIParser(self._ai, self._categories, self._methods,
                                    self._countries, self._types, self._species)
            self.finished.emit(parser.get_bean_from_url(self._url))
        except Exception as e:  # noqa: BLE001
            self.error.emit(str(e))


# ─────────────────────────────────────────────────────────────────────────────
# Selectable choice widgets (mock v2: active = accent border, inactive = dimmed)
# ─────────────────────────────────────────────────────────────────────────────

class _ChoiceCard(QFrame):
    """Large selectable card with a radio dot, a title and a subtitle."""

    clicked = pyqtSignal()

    def __init__(self, title: str, subtitle: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        v = QVBoxLayout(self)
        v.setContentsMargins(15, 12, 15, 12)
        v.setSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(9)
        self._dot = QLabel("")
        self._dot.setFixedSize(13, 13)
        self._title = QLabel(title)
        row.addWidget(self._dot)
        row.addWidget(self._title)
        row.addStretch(1)
        v.addLayout(row)
        self._sub = QLabel(subtitle)
        self._sub.setWordWrap(True)
        self._sub.setContentsMargins(22, 0, 0, 0)
        v.addWidget(self._sub)
        self.set_selected(False)

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        if selected:
            self.setStyleSheet(
                f"_ChoiceCard {{ background: rgba(137,180,250,18);"
                f" border: 1px solid {THEME['ACCENT']}; border-radius: 10px; }}")
            self._title.setStyleSheet(
                f"color:{THEME['TEXT']};font-size:12px;"
                f"font-weight:700;background:transparent;border:none;")
            self._sub.setProperty('variant', 'caption')
            self._dot.setStyleSheet(
                f"background:{THEME['ACCENT']};border:2px solid {THEME['ACCENT']};"
                f"border-radius:6px;")
        else:
            self.setStyleSheet(
                f"_ChoiceCard {{ background: {THEME['SURFACE']};"
                f" border: 1px solid {THEME['BORDER']}; border-radius: 10px; }}")
            self._title.setStyleSheet(
                f"color:{_DIM};font-size:12px;"
                f"font-weight:700;background:transparent;border:none;")
            self._sub.setStyleSheet(
                f"color:{_DIM};font-size:11px;background:transparent;border:none;")
            self._dot.setStyleSheet(
                f"background:transparent;border:2px solid {_DIM};border-radius:6px;")

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class _Pill(QPushButton):
    """Small selectable pill for sub-choices inside a zone."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__("● " + text, parent)
        self._label = text
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggled.connect(self._restyle)
        self._restyle(False)

    def _restyle(self, checked: bool) -> None:
        self.setText(("◉ " if checked else "○ ") + self._label)
        if checked:
            self.setStyleSheet(
                f"QPushButton {{ background: rgba(137,180,250,18); color: {THEME['TEXT']};"
                f" border: 1px solid {THEME['ACCENT']}; border-radius: 8px;"
                f" padding: 6px 14px; font-size: 12px;"
                f" font-weight: 600; text-align: left; }}")
        else:
            self.setStyleSheet(
                f"QPushButton {{ background: {THEME['BG']}; color: {_DIM};"
                f" border: 1px solid {THEME['BORDER']}; border-radius: 8px;"
                f" padding: 6px 14px; font-size: 12px;"
                f" font-weight: 600; text-align: left; }}")


def _exclusive(cards: list) -> None:
    """Wire _ChoiceCards so clicking one selects it and deselects the others."""
    def _select(target) -> None:
        for c in cards:
            c.set_selected(c is target)
    for c in cards:
        c.clicked.connect(lambda t=c: _select(t))


# ─────────────────────────────────────────────────────────────────────────────
# Wizard
# ─────────────────────────────────────────────────────────────────────────────

class NewSackWizard(QDialog):
    """Guided assistant to register a new bag of green coffee."""

    _PAGE_INTRO: Final[int] = 0
    _PAGE_ESSENTIALS: Final[int] = 1
    _PAGE_SACK: Final[int] = 2
    _PAGE_PROVENANCE: Final[int] = 3
    _PAGE_FACTS: Final[int] = 4
    _PAGE_SENSORY: Final[int] = 5
    _PAGE_REVIEW: Final[int] = 6
    # appended last so the indices above keep their historical values
    _PAGE_NEWCROP: Final[int] = 7

    def __init__(self, host, source_bean: GreenBean | None = None) -> None:
        # host: BeancaveDlg — catalogue, save/refresh, AI config, Niimbot.
        # source_bean: skip straight to the new-crop flow for that record.
        super().__init__(host)
        # frameless translucent window: ground=False, else the grounded base
        # paints the rectangle opaque and squares off the rounded card.
        apply_tilau_theme(self, ground=False)
        self._host = host
        self._drag_pos = None
        self._history: list[int] = []
        self._return_to_review = False
        self._ai_used = False
        self._ai_thread: QThread | None = None
        self._ai_worker: _WizardAIWorker | None = None
        self._prefilled_from: GreenBean | None = None
        # locked source record: set only by the "New crop" shortcut
        self._source_bean: GreenBean | None = source_bean
        self._aw_win: QDialog | None = None
        # ⚖ Acaia capture — _ScaleFloatWindow reads `_aw` (tare) and calls
        # `receive_scale_weight` on its parent dialog.
        self._aw = getattr(host, 'aw', None)
        self._scale_window: QDialog | None = None
        self._scale_was_connected = False

        self._page_titles = {
            self._PAGE_ESSENTIALS: QApplication.translate("tilauscope_sacks", "Essentials"),
            self._PAGE_SACK: QApplication.translate("tilauscope_sacks", "Sack ID"),
            self._PAGE_PROVENANCE: QApplication.translate("tilauscope_sacks", "Provenance"),
            self._PAGE_FACTS: QApplication.translate("tilauscope_sacks", "Characteristics"),
            self._PAGE_SENSORY: QApplication.translate("tilauscope_sacks", "Sensory & notes"),
            self._PAGE_REVIEW: QApplication.translate("tilauscope_sacks", "Review"),
            self._PAGE_NEWCROP: QApplication.translate("tilauscope_sacks", "New crop"),
        }

        self.setWindowTitle(QApplication.translate("tilauscope_sacks", "New sack"))
        self.setMinimumWidth(760)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("SackWizardCard")
        card.setStyleSheet(f"""
            #SackWizardCard {{
                background-color : {THEME['BG']};
                border           : 2px solid {THEME['ACCENT']};
                border-radius    : 14px;
            }}
            QLabel {{ color: {THEME['TEXT']}; background: transparent; border: none; }}
            QLineEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit {{
                background: {THEME['BG']}; color: {THEME['TEXT']};
                font-size: 12px;
                selection-background-color: {THEME['ACCENT']};
                selection-color: {THEME['BG']};
                border: 1px solid {THEME['BORDER']}; border-radius: 7px; padding: 5px 8px; }}
            QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
            QPlainTextEdit:focus {{
                border: 1px solid {THEME['ACCENT']};
                background: {THEME['SURFACE']}; }}
            QComboBox {{ background: {THEME['BG']}; color: {THEME['TEXT']};
                font-size: 12px;
                selection-background-color: {THEME['ACCENT']};
                selection-color: {THEME['BG']};
                border: 1px solid {THEME['BORDER']}; border-radius: 7px; padding: 5px 8px; }}
            QComboBox:focus {{ border: 1px solid {THEME['ACCENT']}; }}
            QComboBox QAbstractItemView {{ background: {THEME['SURFACE']};
                color: {THEME['TEXT']}; selection-background-color: {THEME['ACCENT']};
                selection-color: {THEME['BG']}; }}
        """)
        outer.addWidget(card)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(26, 18, 26, 20)
        lay.setSpacing(14)

        # ── Title bar ────────────────────────────────────────────────────────
        title_row = QHBoxLayout()
        title_lbl = QLabel(
            QApplication.translate("tilauscope_sacks", "NEW CROP") if source_bean is not None
            else QApplication.translate("tilauscope_sacks", "NEW SACK"))
        title_lbl.setStyleSheet(
            f"color:{THEME['ACCENT']};font-size:14px;"
            f"font-weight:800;letter-spacing:3px;")
        title_row.addWidget(title_lbl)
        self.step_lbl = QLabel("")
        self.step_lbl.setProperty('variant', 'eyebrow')
        title_row.addSpacing(16)
        title_row.addWidget(self.step_lbl)
        title_row.addStretch(1)
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(24, 24)
        close_btn.setProperty('variant', 'icon')   # fixed size: no base padding
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {THEME['SUBTEXT']};"
            f" border: none; font-size: 14px; padding: 0; }}"
            f"QPushButton:hover {{ color: {THEME['CRITICAL']}; }}")
        close_btn.clicked.connect(self.reject)
        title_row.addWidget(close_btn)
        lay.addLayout(title_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {THEME['BORDER']};")
        lay.addWidget(sep)

        # ── Pages ────────────────────────────────────────────────────────────
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_intro_page())        # 0
        self.stack.addWidget(self._build_essentials_page())   # 1
        self.stack.addWidget(self._build_sack_page())         # 2
        self.stack.addWidget(self._build_provenance_page())   # 3
        self.stack.addWidget(self._build_facts_page())        # 4
        self.stack.addWidget(self._build_sensory_page())      # 5
        self.stack.addWidget(self._build_review_page())       # 6
        self.stack.addWidget(self._build_newcrop_page())      # 7
        lay.addWidget(self.stack, 1)

        # ── Navigation footer — every action lives here (mock v2) ───────────
        nav_sep = QFrame()
        nav_sep.setFrameShape(QFrame.Shape.HLine)
        nav_sep.setStyleSheet(f"color: {THEME['BORDER']};")
        lay.addWidget(nav_sep)
        nav = QHBoxLayout()
        self.back_btn = QPushButton("◂ " + QApplication.translate("tilauscope_sacks", "Back"))
        self.back_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {THEME['TEXT']};"
            f" border: 1px solid {THEME['BORDER']}; border-radius: 7px;"
            f" font-weight: 700;"
            f" padding: 8px 18px; }}"
            f"QPushButton:hover {{ border-color: {THEME['ACCENT']}; }}")
        self.back_btn.clicked.connect(self._on_back)
        self.skip_btn = QPushButton(QApplication.translate("tilauscope_sacks", "Skip") + " ▸")
        self.skip_btn.setStyleSheet(self.back_btn.styleSheet())
        self.skip_btn.clicked.connect(self._on_skip)
        self.next_btn = QPushButton(QApplication.translate("tilauscope_sacks", "Next") + " ▸")
        self.next_btn.setStyleSheet(
            f"QPushButton {{ background: {THEME['ACCENT']}; color: {THEME['BG']};"
            f" border: none; border-radius: 7px; "
            f" font-weight: 700; padding: 8px 20px; }}"
            f"QPushButton:disabled {{ background: {THEME['BORDER']};"
            f" color: {THEME['SUBTEXT']}; }}")
        self.next_btn.clicked.connect(self._on_next)
        self.start_btn = QPushButton(QApplication.translate("tilauscope_sacks", "Start") + " ▸")
        self.start_btn.setStyleSheet(self.next_btn.styleSheet())
        self.start_btn.clicked.connect(self._on_start)
        self.create_btn = QPushButton("✓ " + QApplication.translate("tilauscope_sacks", "Create the sack"))
        self.create_btn.setStyleSheet(
            f"QPushButton {{ background: {THEME['SUCCESS']}; color: {THEME['BG']};"
            f" border: none; border-radius: 7px; "
            f" font-weight: 700; padding: 8px 20px; }}")
        self.create_btn.clicked.connect(self._create)
        nav.addWidget(self.back_btn)
        nav.addStretch(1)
        nav.addWidget(self.skip_btn)
        nav.addWidget(self.start_btn)
        nav.addWidget(self.next_btn)
        nav.addWidget(self.create_btn)
        lay.addLayout(nav)

        if source_bean is not None:
            self._goto(self._PAGE_NEWCROP)
        else:
            self._goto(self._PAGE_INTRO)

        # Return must not reach the ✕ / Cancel this dialog builds first
        # (tilauscope_types.no_enter_default).
        no_enter_default(self)

    # ── Frameless drag ────────────────────────────────────────────────────────
    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    # ── Style helpers (ROAST SETUP visual language) ───────────────────────────
    def _section(self, text: str, optional: bool = False) -> QLabel:
        suffix = (f"  <span style='color:{_DIM};font-weight:600;"
                  f"letter-spacing:1px;'>· " + QApplication.translate("tilauscope_sacks", "optional") + "</span>") if optional else ""
        w = QLabel(text.upper() + suffix)
        w.setTextFormat(Qt.TextFormat.RichText)
        w.setStyleSheet(
            f"color:{THEME['ACCENT']};font-size:11px;"
            f"font-weight:800;letter-spacing:2px;")
        return w

    def _zone(self) -> tuple[QFrame, QVBoxLayout]:
        z = QFrame()
        z.setObjectName("WizZone")
        z.setStyleSheet(
            f"QFrame#WizZone {{ background: {THEME['SURFACE']};"
            f" border: 1px solid {THEME['BORDER']}; border-radius: 10px; }}")
        zl = QVBoxLayout(z)
        zl.setContentsMargins(16, 13, 16, 13)
        zl.setSpacing(11)
        return z, zl

    def _hint(self, text: str) -> QLabel:
        w = QLabel(text)
        w.setWordWrap(True)
        w.setProperty('variant', 'caption')
        return w

    def _ghost_btn(self, text: str) -> QPushButton:
        b = QPushButton(text)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {THEME['ACCENT']};"
            f" border: 1px solid {THEME['BORDER']}; border-radius: 6px;"
            f" padding: 6px 13px; font-size: 11px;"
            f" font-weight: 600; }}"
            f"QPushButton:hover {{ border-color: {THEME['ACCENT']}; }}")
        return b

    # ── Page 0 : start ────────────────────────────────────────────────────────
    def _build_intro_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setSpacing(12)

        v.addWidget(self._section(QApplication.translate("tilauscope_sacks", "How do you want to start?")))

        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.card_ai = _ChoiceCard(
            "🤖 " + QApplication.translate("tilauscope_sacks", "Pre-fill with AI"),
            QApplication.translate("tilauscope_sacks", "Paste the supplier's product page URL — the assistant fills "
                "the bean description, you only review."))
        self.card_manual = _ChoiceCard(
            "📝 " + QApplication.translate("tilauscope_sacks", "Fill in step by step"),
            QApplication.translate("tilauscope_sacks", "Six short steps; only the first one is required, everything "
                "else can be skipped."))
        _exclusive([self.card_ai, self.card_manual])
        self.card_ai.clicked.connect(lambda: self._url_zone.setVisible(True))
        self.card_manual.clicked.connect(lambda: self._url_zone.setVisible(False))
        cards.addWidget(self.card_ai, 1)
        cards.addWidget(self.card_manual, 1)
        v.addLayout(cards)

        ai_available = bool(getattr(getattr(self._host, 'ai', None), 'apikey', ''))
        self._url_zone, uz = self._zone()
        url_row = QHBoxLayout()
        url_row.setSpacing(10)
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText(QApplication.translate("tilauscope_sacks", "Enter URL of supplier here..."))
        paste_btn = self._ghost_btn(QApplication.translate("tilauscope_sacks", "Paste"))
        paste_btn.clicked.connect(
            lambda: self.url_edit.setText(QGuiApplication.clipboard().text()))
        url_row.addWidget(self.url_edit, 1)
        url_row.addWidget(paste_btn)
        uz.addLayout(url_row)
        uz.addWidget(self._hint(QApplication.translate("tilauscope_sacks",
            "The extraction runs in the background — you land on the "
            "identification step with everything pre-filled.")))
        self.ai_status_lbl = QLabel("")
        self.ai_status_lbl.setWordWrap(True)
        self.ai_status_lbl.setStyleSheet(f"color: {THEME['ACCENT']}; font-size: 11px;")
        self.ai_status_lbl.hide()
        uz.addWidget(self.ai_status_lbl)
        v.addWidget(self._url_zone)

        if ai_available:
            self.card_ai.set_selected(True)
            self.card_manual.set_selected(False)
        else:
            self.card_ai.setEnabled(False)
            self.card_ai.setToolTip(QApplication.translate("tilauscope_sacks",
                "Configure an AI engine and API key in TilauScope settings to "
                "enable this."))
            self.card_manual.set_selected(True)
            self._url_zone.hide()

        v.addStretch(1)
        return page

    def _on_start(self) -> None:
        if self.card_ai._selected:
            self._start_ai()
        else:
            self._history.append(self._PAGE_INTRO)
            self._goto(self._PAGE_ESSENTIALS)

    # ── AI flow ───────────────────────────────────────────────────────────────
    def _start_ai(self) -> None:
        url = self.url_edit.text().strip()
        if not url:
            self.url_edit.setFocus()
            return

        # Who receives the page text must be named once per provider.
        from tilauscope.tilau_privacy_ui import (  # noqa: PLC0415
            Gate, ensure_ai_disclosure, show_roast_blocked,
        )
        gate = ensure_ai_disclosure(self, getattr(self._host, 'ai', None), getattr(self._host, 'aw', None))
        if gate is Gate.BLOCKED_ROAST:
            show_roast_blocked(self)
            return
        if gate is not Gate.ALLOW:
            return

        self.start_btn.setEnabled(False)
        self.ai_status_lbl.setText("⏳ " + QApplication.translate("tilauscope_sacks", "Fetching and analyzing website content..."))
        self.ai_status_lbl.show()

        self._ai_thread = QThread()
        self._ai_worker = _WizardAIWorker(self._host, url)
        self._ai_worker.moveToThread(self._ai_thread)
        self._ai_thread.started.connect(self._ai_worker.run)
        self._ai_worker.finished.connect(self._on_ai_finished)
        self._ai_worker.error.connect(self._on_ai_error)
        for sig in (self._ai_worker.finished, self._ai_worker.error):
            sig.connect(self._ai_thread.quit)
            sig.connect(self._ai_worker.deleteLater)
        self._ai_thread.finished.connect(self._ai_thread.deleteLater)
        self._ai_thread.start()

    def _on_ai_finished(self, bean) -> None:
        self.start_btn.setEnabled(True)
        self.ai_status_lbl.hide()
        if not isinstance(bean, GreenBean):
            self._on_ai_error(QApplication.translate("tilauscope_sacks", "No data could be extracted from this page."))
            return
        self._ai_used = True
        self.card_new.set_selected(True)
        self.card_catalogue.set_selected(False)
        self._refresh_essentials_mode()
        self._apply_bean_to_widgets(bean)
        # Land on the sack-id step (skippable) — review comes right after.
        self._history = [self._PAGE_INTRO, self._PAGE_ESSENTIALS]
        self._goto(self._PAGE_SACK)

    def _on_ai_error(self, message: str) -> None:
        self.start_btn.setEnabled(True)
        self.ai_status_lbl.hide()
        show_styled_message(self, QApplication.translate("tilauscope_sacks", "AI Error"),
                            QApplication.translate("tilauscope_sacks", "Failed to extract bean data") + f": {message}",
                            QMessageBox.Icon.Warning)

    # ── Page 1 : essentials ───────────────────────────────────────────────────
    def _build_essentials_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setSpacing(12)

        v.addWidget(self._section(QApplication.translate("tilauscope_sacks", "This sack contains")))

        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.card_new = _ChoiceCard(
            "🫘 " + QApplication.translate("tilauscope_sacks", "A new bean"),
            QApplication.translate("tilauscope_sacks", "First bag of a coffee not yet in your catalogue."))
        self.card_catalogue = _ChoiceCard(
            "📦 " + QApplication.translate("tilauscope_sacks", "A bean already in the catalogue"),
            QApplication.translate("tilauscope_sacks", "Restock, or a new crop of a coffee you know."))
        _exclusive([self.card_new, self.card_catalogue])
        self.card_new.clicked.connect(self._refresh_essentials_mode)
        self.card_catalogue.clicked.connect(self._refresh_essentials_mode)
        self.card_new.set_selected(True)
        cards.addWidget(self.card_new, 1)
        cards.addWidget(self.card_catalogue, 1)
        v.addLayout(cards)

        # -- new bean zone
        self._new_section = self._section(QApplication.translate("tilauscope_sacks", "New bean"))
        v.addWidget(self._new_section)
        self._new_zone, nz = self._zone()
        nf = QFormLayout()
        # macOS style pins fields to their size hint — let text fields breathe
        nf.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        nf.setHorizontalSpacing(14)
        nf.setVerticalSpacing(10)
        self.name_edit = QLineEdit()
        self.country_combo = QComboBox()
        self.country_combo.addItems(getattr(self._host, 'coffee_producing_countries', []) or [])
        self.crop_spin = QSpinBox()
        self.crop_spin.setRange(2000, 2100)
        self.crop_spin.setValue(datetime.now().astimezone().year)
        self.weight_spin = QDoubleSpinBox()
        self.weight_spin.setRange(0.0, 100000.0)
        self.weight_spin.setDecimals(0)
        self.weight_spin.setSuffix(" g")
        self.weight_spin.setValue(1000.0)
        nf.addRow(QApplication.translate("tilauscope_sacks", "Bean name:"), self.name_edit)
        nf.addRow(QApplication.translate("tilauscope_sacks", "Origin / country:"), self.country_combo)
        nf.addRow(QApplication.translate("tilauscope_sacks", "Harvest year:"), self.crop_spin)
        nf.addRow(QApplication.translate("tilauscope_sacks", "Initial weight (stock):"), self.weight_spin)
        nz.addLayout(nf)
        v.addWidget(self._new_zone)

        # -- catalogue bean zone
        self._cat_section = self._section(QApplication.translate("tilauscope_sacks", "Catalogue bean"))
        v.addWidget(self._cat_section)
        self._cat_zone, cz = self._zone()
        self.existing_combo = QComboBox()
        self.existing_combo.currentIndexChanged.connect(self._refresh_essentials_mode)
        cz.addWidget(self.existing_combo)
        pills = QHBoxLayout()
        pills.setSpacing(10)
        self.pill_restock = _Pill(QApplication.translate("tilauscope_sacks", "Restock — same crop"))
        self.pill_newcrop = _Pill(QApplication.translate("tilauscope_sacks", "New crop of the same bean"))
        self.pill_restock.setChecked(True)
        self.pill_restock.clicked.connect(lambda: self._pick_pill(self.pill_restock))
        self.pill_newcrop.clicked.connect(lambda: self._pick_pill(self.pill_newcrop))
        pills.addWidget(self.pill_restock)
        pills.addWidget(self.pill_newcrop)
        pills.addStretch(1)
        cz.addLayout(pills)

        # restock sub-form
        self._restock_w = QWidget()
        rl = QVBoxLayout(self._restock_w)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)
        rf = QFormLayout()
        rf.setHorizontalSpacing(14)
        self.restock_weight_spin = QDoubleSpinBox()
        self.restock_weight_spin.setRange(0.0, 100000.0)
        self.restock_weight_spin.setDecimals(0)
        self.restock_weight_spin.setSuffix(" g")
        self.restock_weight_spin.setValue(1000.0)
        rf.addRow(QApplication.translate("tilauscope_sacks", "Weight of the new sack:"), self.restock_weight_spin)
        rl.addLayout(rf)
        self.restock_hint = self._hint("")
        rl.addWidget(self.restock_hint)
        cz.addWidget(self._restock_w)

        # new crop sub-form — the fields themselves live on the New crop page
        self._newcrop_w = QWidget()
        cl = QVBoxLayout(self._newcrop_w)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(8)
        cl.addWidget(self._hint(QApplication.translate("tilauscope_sacks",
            "The next step asks for the new harvest: year, weight, supplier "
            "and the three measurements of the lot. Origin, process and "
            "variety are inherited from the record above.")))
        cz.addWidget(self._newcrop_w)
        v.addWidget(self._cat_zone)

        v.addStretch(1)
        self._populate_existing_combo()
        return page

    def _pick_pill(self, target: _Pill) -> None:
        for p in (self.pill_restock, self.pill_newcrop):
            p.setChecked(p is target)
        self._refresh_essentials_mode()

    def _populate_existing_combo(self) -> None:
        self.existing_combo.clear()
        beans = getattr(getattr(self._host, 'cave', None), 'green_beans', None) or []
        for b in beans:
            label = b.name if not b.country else f"{b.name} · {b.country}"
            if b.crop:
                label += f" · {b.crop}"
            self.existing_combo.addItem(label, b.uuid)
        if not beans:
            self.card_catalogue.setEnabled(False)
            self.card_catalogue.setToolTip(QApplication.translate("tilauscope_sacks", "Your catalogue is still empty."))

    def _selected_source_bean(self) -> GreenBean | None:
        if self._source_bean is not None:
            return self._source_bean
        uid = self.existing_combo.currentData()
        beans = getattr(getattr(self._host, 'cave', None), 'green_beans', None) or []
        for b in beans:
            if b.uuid == uid:
                return b
        return None

    def _mode(self) -> str:
        if self._source_bean is not None:
            return "newcrop"
        if self.card_new._selected:
            return "new"
        return "restock" if self.pill_restock.isChecked() else "newcrop"

    def _refresh_essentials_mode(self) -> None:
        mode = self._mode()
        is_new = mode == "new"
        self._new_section.setVisible(is_new)
        self._new_zone.setVisible(is_new)
        self._cat_section.setVisible(not is_new)
        self._cat_zone.setVisible(not is_new)
        self._restock_w.setVisible(mode == "restock")
        self._newcrop_w.setVisible(mode == "newcrop")
        src = self._selected_source_bean()
        if src is not None:
            added = self.restock_weight_spin.value()
            self.restock_hint.setText(
                QApplication.translate("tilauscope_sacks", "Added to the current stock") +
                f" ({src.weight_left:.0f} g → {src.weight_left + added:.0f} g). " +
                QApplication.translate("tilauscope_sacks", "Nothing else on the record changes."))

    # ── Page 7 : new crop of a catalogue bean ─────────────────────────────────
    def _build_newcrop_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setSpacing(12)

        # -- inherited identity (read only)
        v.addWidget(self._section(QApplication.translate("tilauscope_sacks", "Same coffee, next harvest")))
        sz, szl = self._zone()
        self.nc_source_lbl = QLabel("")
        self.nc_source_lbl.setWordWrap(True)
        self.nc_source_lbl.setStyleSheet(
            f"color:{THEME['TEXT']};font-size:14px;font-weight:800;")
        self.nc_source_sub = QLabel("")
        self.nc_source_sub.setWordWrap(True)
        self.nc_source_sub.setProperty('variant', 'secondary')
        szl.addWidget(self.nc_source_lbl)
        szl.addWidget(self.nc_source_sub)
        szl.addWidget(self._hint(QApplication.translate("tilauscope_sacks",
            "Origin, process, variety and altitude are copied as they are.")))
        v.addWidget(sz)

        # -- what belongs to the new sack
        v.addWidget(self._section(QApplication.translate("tilauscope_sacks", "The new sack")))
        nz, nzl = self._zone()
        nf = QFormLayout()
        nf.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        nf.setHorizontalSpacing(14)
        nf.setVerticalSpacing(10)
        self.newcrop_crop_spin = QSpinBox()
        self.newcrop_crop_spin.setRange(2000, 2100)
        self.newcrop_weight_spin = QDoubleSpinBox()
        self.newcrop_weight_spin.setRange(0.0, 100000.0)
        self.newcrop_weight_spin.setDecimals(0)
        self.newcrop_weight_spin.setSuffix(" g")
        self.newcrop_weight_spin.setValue(1000.0)
        self.nc_supplier_edit = QLineEdit()
        # the provenance page stays the single source of truth for the record
        self.nc_supplier_edit.textChanged.connect(self._mirror_supplier)
        nf.addRow(QApplication.translate("tilauscope_sacks", "Harvest year:"), self.newcrop_crop_spin)
        nf.addRow(QApplication.translate("tilauscope_sacks", "Weight received:"), self.newcrop_weight_spin)
        nf.addRow(QApplication.translate("tilauscope_sacks", "Supplier:"), self.nc_supplier_edit)
        nzl.addLayout(nf)
        v.addWidget(nz)

        # -- the three lot measurements: never inherited silently
        head = QHBoxLayout()
        head.addWidget(self._section(QApplication.translate("tilauscope_sacks", "Measured on this lot")))
        head.addStretch(1)
        self.nc_copy_btn = self._ghost_btn("")
        self.nc_copy_btn.setToolTip(QApplication.translate("tilauscope_sacks",
            "Reuse the previous harvest's values as a starting point. They are "
            "a guess until you measure this lot."))
        self.nc_copy_btn.clicked.connect(self._copy_previous_measurements)
        head.addWidget(self.nc_copy_btn)
        v.addLayout(head)

        mz, mzl = self._zone()
        mzl.addWidget(self._hint(QApplication.translate("tilauscope_sacks",
            "These three drive the roast plan and change with every harvest. "
            "Leave a field empty if you have not measured it yet.")))
        mf = QFormLayout()
        mf.setHorizontalSpacing(14)
        mf.setVerticalSpacing(10)
        self.nc_density_spin = QDoubleSpinBox()
        self.nc_density_spin.setRange(0.0, 1000.0)
        self.nc_density_spin.setDecimals(1)
        self.nc_density_spin.setSuffix(" g/L")
        self.nc_humidity_spin = QDoubleSpinBox()
        self.nc_humidity_spin.setRange(0.0, 30.0)
        self.nc_humidity_spin.setDecimals(1)
        self.nc_humidity_spin.setSuffix(" %")
        self.nc_wa_spin = QDoubleSpinBox()
        self.nc_wa_spin.setRange(0.0, 1.0)
        self.nc_wa_spin.setDecimals(2)
        self.nc_wa_spin.setSingleStep(0.01)
        self.nc_wa_spin.setSuffix(" aw")
        self.nc_density_ref = self._hint("")
        self.nc_humidity_ref = self._hint("")
        self.nc_wa_ref = self._hint("")
        for spin, ref, mirror in (
                (self.nc_density_spin, self.nc_density_ref, 'density_spin'),
                (self.nc_humidity_spin, self.nc_humidity_ref, 'humidity_spin'),
                (self.nc_wa_spin, self.nc_wa_ref, 'wa_spin')):
            # 0 reads as "not measured" — show nothing rather than a false 0.0
            spin.setSpecialValueText(" ")
            spin.valueChanged.connect(
                lambda val, name=mirror: getattr(self, name).setValue(float(val)))
            row = QHBoxLayout()
            row.setSpacing(12)
            row.addWidget(spin)
            row.addWidget(ref, 1)
            holder = QWidget()
            holder.setLayout(row)
            label = {self.nc_density_spin: QApplication.translate("tilauscope_sacks", "Density:"),
                     self.nc_humidity_spin: QApplication.translate("tilauscope_sacks", "Humidity:"),
                     self.nc_wa_spin: QApplication.translate("tilauscope_sacks", "Water activity:")}[spin]
            mf.addRow(label, holder)
        mzl.addLayout(mf)
        v.addWidget(mz)

        # -- secondary: sensory carried over, collapsed by default
        self.nc_more_btn = QPushButton("")
        self.nc_more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.nc_more_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {THEME['ACCENT']};"
            f" border: none; padding: 2px 0; font-size: 11px;"
            f" font-weight: 600; text-align: left; }}")
        self.nc_more_btn.clicked.connect(self._toggle_newcrop_more)
        v.addWidget(self.nc_more_btn)

        self.nc_more_w, mwl = self._zone()
        mwf = QFormLayout()
        mwf.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        mwf.setHorizontalSpacing(14)
        mwf.setVerticalSpacing(10)
        self.nc_flavour_edit = QLineEdit()
        self.nc_flavour_edit.textChanged.connect(self._mirror_flavour)
        self.nc_sca_spin = QDoubleSpinBox()
        self.nc_sca_spin.setRange(0.0, 100.0)
        self.nc_sca_spin.setDecimals(1)
        self.nc_sca_spin.valueChanged.connect(
            lambda val: self.sca_spin.setValue(float(val)))
        mwf.addRow(QApplication.translate("tilauscope_sacks", "Flavour notes:"), self.nc_flavour_edit)
        mwf.addRow(QApplication.translate("tilauscope_sacks", "Score:"), self.nc_sca_spin)
        mwl.addLayout(mwf)
        self.nc_retire_chk = QCheckBox("")
        self.nc_retire_chk.setStyleSheet(
            f"QCheckBox {{ color: {THEME['TEXT']}; font-size: 11.5px; }}")
        mwl.addWidget(self.nc_retire_chk)
        self.nc_more_w.hide()
        v.addWidget(self.nc_more_w)

        v.addStretch(1)
        return page

    def _mirror_supplier(self, text: str) -> None:
        self.supplier_edit.setText(text)

    def _mirror_flavour(self, text: str) -> None:
        self.flavour_edit.setText(text)

    def _toggle_newcrop_more(self) -> None:
        self.nc_more_w.setVisible(not self.nc_more_w.isVisible())
        self._refresh_newcrop_more_label()

    def _refresh_newcrop_more_label(self) -> None:
        src = self._selected_source_bean()
        year = str(src.crop) if src is not None and src.crop else "—"
        arrow = "▾" if self.nc_more_w.isVisible() else "▸"
        self.nc_more_btn.setText(
            f"{arrow} " + QApplication.translate("tilauscope_sacks",
                "Sensory and score — copied from {0}, open this to adjust").format(year))

    def _copy_previous_measurements(self) -> None:
        src = self._selected_source_bean()
        if src is None:
            return
        self.nc_density_spin.setValue(src.density or 0.0)
        self.nc_humidity_spin.setValue(src.last_humidity or 0.0)
        self.nc_wa_spin.setValue(src.water_activity or 0.0)

    def _refresh_newcrop(self) -> None:
        src = self._selected_source_bean()
        if src is None:
            return
        year = str(src.crop) if src.crop else "—"
        self.nc_source_lbl.setText("🫘  " + self._join(
            [src.name, src.country, str(src.crop) if src.crop else ""]))
        self.nc_source_sub.setText(self._join(
            [src.process, src.varieties, f"{src.altitude} m" if src.altitude else "",
             src.supplier, src.species]))
        self.nc_copy_btn.setText(
            QApplication.translate("tilauscope_sacks", "Copy {0} values").format(year))
        self.nc_density_ref.setText(
            QApplication.translate("tilauscope_sacks", "{0} was {1} g/L").format(year, f"{src.density:.1f}")
            if src.density else "")
        self.nc_humidity_ref.setText(
            QApplication.translate("tilauscope_sacks", "{0} was {1} %").format(year, f"{src.last_humidity:.1f}")
            if src.last_humidity else "")
        self.nc_wa_ref.setText(
            QApplication.translate("tilauscope_sacks", "{0} was {1} aw").format(year, f"{src.water_activity:.2f}")
            if src.water_activity else "")
        self.nc_retire_chk.setText(
            QApplication.translate("tilauscope_sacks",
                "This crop replaces the previous one — set {0} stock to 0").format(year))
        self._refresh_newcrop_more_label()
        if self._prefilled_from is not src:
            # proposed once per source record, never against an operator edit
            self._prefill_from_source()
            self.newcrop_crop_spin.setValue(
                (src.crop + 1) if src.crop else datetime.now().astimezone().year)
        # the Characteristics page can be reached from Review — take back what
        # was edited there so both views show the same measurements
        for nc_spin, main_spin in ((self.nc_density_spin, self.density_spin),
                                   (self.nc_humidity_spin, self.humidity_spin),
                                   (self.nc_wa_spin, self.wa_spin)):
            if nc_spin.value() != main_spin.value():
                nc_spin.blockSignals(True)
                nc_spin.setValue(main_spin.value())
                nc_spin.blockSignals(False)

    # ── Page 2 : sack identification ──────────────────────────────────────────
    def _build_sack_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setSpacing(12)

        v.addWidget(self._section(QApplication.translate("tilauscope_sacks", "Sack identification"), optional=True))
        z, zl = self._zone()
        zl.addWidget(self._hint(QApplication.translate("tilauscope_sacks",
            "Do you label your bags? Type or pick the sack number here so the "
            "bean record keeps track of the physical bag. If you don't label "
            "your bags, simply skip this step — nothing depends on it.")))

        row = QHBoxLayout()
        row.setSpacing(12)
        self.sack_combo = QComboBox()
        self.sack_combo.setEditable(True)
        self.sack_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.sack_combo.setMinimumWidth(200)
        self.sack_combo.editTextChanged.connect(self._check_sack_duplicate)
        row.addWidget(self.sack_combo)
        self.free_tag = QLabel("")
        self.free_tag.setStyleSheet(
            f"color:{THEME['SUCCESS']};font-size:10.5px;"
            f"border:1px solid rgba(166,227,161,90);border-radius:5px;"
            f"padding:2px 8px;background:transparent;")
        self.free_tag.hide()
        row.addWidget(self.free_tag)
        row.addStretch(1)
        zl.addLayout(row)

        self.dup_warn_lbl = QLabel("")
        self.dup_warn_lbl.setWordWrap(True)
        self.dup_warn_lbl.setStyleSheet(f"color: {THEME['WARNING']}; font-size: 11px;")
        self.dup_warn_lbl.hide()
        zl.addWidget(self.dup_warn_lbl)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        print_btn = self._ghost_btn("🖨 " + QApplication.translate("tilauscope_sacks", "Print a batch of ID labels"))
        print_btn.setToolTip(QApplication.translate("tilauscope_sacks", "Open the label tool to print a numbered batch "
                                 "of sack labels on the Niimbot."))
        print_btn.clicked.connect(lambda: self._open_labels_tool(0))
        reprint_btn = self._ghost_btn(QApplication.translate("tilauscope_sacks", "Reprint a label"))
        reprint_btn.setToolTip(QApplication.translate("tilauscope_sacks", "Reprint one damaged or lost label without "
                                   "touching the number sequence."))
        reprint_btn.clicked.connect(lambda: self._open_labels_tool(1))
        btn_row.addWidget(print_btn)
        btn_row.addWidget(reprint_btn)
        btn_row.addStretch(1)
        zl.addLayout(btn_row)
        v.addWidget(z)

        v.addStretch(1)
        return page

    def _refresh_sack_pool(self) -> None:
        current = self.sack_combo.currentText()
        beans = getattr(getattr(self._host, 'cave', None), 'green_beans', None) or []
        self.sack_combo.blockSignals(True)
        self.sack_combo.clear()
        free = set(SackPool.free_ids())
        available = SackPool.available_ids(beans)
        for sack_id in available:
            self.sack_combo.addItem(sack_id)
            idx = self.sack_combo.count() - 1
            tip = (QApplication.translate("tilauscope_sacks", "Recycled label from an emptied sack") if sack_id in free
                   else QApplication.translate("tilauscope_sacks", "Printed label, not assigned yet"))
            self.sack_combo.setItemData(idx, tip, Qt.ItemDataRole.ToolTipRole)
        self.sack_combo.setEditText(current)
        self.sack_combo.blockSignals(False)
        if available:
            self.free_tag.setText(
                QApplication.translate("tilauscope_sacks", "{0} label(s) available").format(len(available)))
            self.free_tag.show()
        else:
            self.free_tag.hide()
        self._check_sack_duplicate(self.sack_combo.currentText())

    def _check_sack_duplicate(self, text: str) -> None:
        sack_id = text.strip()
        owner = None
        if sack_id:
            beans = getattr(getattr(self._host, 'cave', None), 'green_beans', None) or []
            owner = SackPool.find_owner(sack_id, beans)
            if owner is not None and self._mode() == "restock":
                src = self._selected_source_bean()
                if src is not None and sack_id in (src.sacks or []):
                    owner = None   # already attached to the very bean we restock
        if owner:
            self.dup_warn_lbl.setText(
                "⚠ " + QApplication.translate("tilauscope_sacks", "This sack number is already assigned to")
                + f" « {owner} ». " + QApplication.translate("tilauscope_sacks", "You can still use it, but double-check "
                                          "the physical bags."))
            self.dup_warn_lbl.show()
        else:
            self.dup_warn_lbl.hide()

    def _open_labels_tool(self, initial_tab: int = 0) -> None:
        try:
            SackLabelsDialog(self._host, initial_tab=initial_tab).exec()
        except Exception:  # noqa: BLE001
            _logd.exception("sack wizard: labels tool failed")
        self._refresh_sack_pool()

    # ── Page 3 : provenance ───────────────────────────────────────────────────
    def _build_provenance_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setSpacing(12)
        v.addWidget(self._section(QApplication.translate("tilauscope_sacks", "Provenance"), optional=True))
        z, zl = self._zone()
        zl.addWidget(self._hint(QApplication.translate("tilauscope_sacks",
            "Where this coffee comes from. Leave anything blank if you don't "
            "know it — you can complete the record later in the bean form.")))
        f = QFormLayout()
        f.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        f.setHorizontalSpacing(14)
        f.setVerticalSpacing(10)
        self.farm_edit = QLineEdit()
        self.farm_edit.setMinimumWidth(340)
        self.supplier_edit = QLineEdit()
        self.supplier_edit.setMinimumWidth(340)
        self.altitude_spin = QSpinBox()
        self.altitude_spin.setRange(0, 5000)
        self.altitude_spin.setSuffix(" m")
        f.addRow(QApplication.translate("tilauscope_sacks", "Farm:"), self.farm_edit)
        f.addRow(QApplication.translate("tilauscope_sacks", "Supplier:"), self.supplier_edit)
        f.addRow(QApplication.translate("tilauscope_sacks", "Altitude:"), self.altitude_spin)
        zl.addLayout(f)
        v.addWidget(z)
        v.addStretch(1)
        return page

    # ── Page 4 : type & bean facts ────────────────────────────────────────────
    def _build_facts_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setSpacing(12)

        # -- type zone (single origin / blend)
        v.addWidget(self._section(QApplication.translate("tilauscope_sacks", "Type")))
        tz, tzl = self._zone()
        pills = QHBoxLayout()
        pills.setSpacing(10)
        self.pill_single = _Pill(QApplication.translate("tilauscope_sacks", "Single origin"))
        self.pill_blend = _Pill(QApplication.translate("tilauscope_sacks", "Blend"))
        self.pill_single.setChecked(True)
        self.pill_single.clicked.connect(lambda: self._pick_type(self.pill_single))
        self.pill_blend.clicked.connect(lambda: self._pick_type(self.pill_blend))
        pills.addWidget(self.pill_single)
        pills.addWidget(self.pill_blend)
        pills.addStretch(1)
        tzl.addLayout(pills)

        self._blend_w = QWidget()
        bl = QFormLayout(self._blend_w)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setHorizontalSpacing(14)
        bl.setVerticalSpacing(10)
        self.bean1_ratio_spin = QDoubleSpinBox()
        self.bean1_ratio_spin.setRange(0.0, 100.0)
        self.bean1_ratio_spin.setDecimals(0)
        self.bean1_ratio_spin.setSuffix(" %")
        self.bean1_ratio_spin.setValue(50.0)
        blend_names = (getattr(self._host, 'coffee_bean_types', {}) or {}).get('Arabica', [])
        self.bean2_combo = QComboBox()
        self.bean2_combo.setEditable(True)
        self.bean2_combo.addItems(blend_names)
        self.bean2_combo.setEditText("")
        self.bean2_ratio_spin = QDoubleSpinBox()
        self.bean2_ratio_spin.setRange(0.0, 100.0)
        self.bean2_ratio_spin.setDecimals(0)
        self.bean2_ratio_spin.setSuffix(" %")
        self.bean2_ratio_spin.setValue(50.0)
        self.bean3_combo = QComboBox()
        self.bean3_combo.setEditable(True)
        self.bean3_combo.addItems(blend_names)
        self.bean3_combo.setEditText("")
        self.bean3_ratio_spin = QDoubleSpinBox()
        self.bean3_ratio_spin.setRange(0.0, 100.0)
        self.bean3_ratio_spin.setDecimals(0)
        self.bean3_ratio_spin.setSuffix(" %")
        row2 = QHBoxLayout()
        row2.setSpacing(10)
        row2.addWidget(self.bean2_combo, 1)
        row2.addWidget(self.bean2_ratio_spin)
        row2w = QWidget()
        row2w.setLayout(row2)
        row3 = QHBoxLayout()
        row3.setSpacing(10)
        row3.addWidget(self.bean3_combo, 1)
        row3.addWidget(self.bean3_ratio_spin)
        row3w = QWidget()
        row3w.setLayout(row3)
        bl.addRow(QApplication.translate("tilauscope_sacks", "This bean's share:"), self.bean1_ratio_spin)
        bl.addRow(QApplication.translate("tilauscope_sacks", "Component 2:"), row2w)
        bl.addRow(QApplication.translate("tilauscope_sacks", "Component 3:"), row3w)
        self._blend_w.hide()
        tzl.addWidget(self._blend_w)
        v.addWidget(tz)

        # -- characteristics zone
        v.addWidget(self._section(QApplication.translate("tilauscope_sacks", "Bean characteristics"), optional=True))
        z, zl = self._zone()
        zl.addWidget(self._hint(QApplication.translate("tilauscope_sacks",
            "Physical data, usually found on the supplier sheet. Density and "
            "humidity feed the roast plan — fill them in if you have them.")))
        f = QFormLayout()
        f.setHorizontalSpacing(14)
        f.setVerticalSpacing(10)
        # category drives the process list — they live side by side (user request)
        self.category_combo = QComboBox()
        self.category_combo.addItems(getattr(self._host, 'coffee_beans_categories', []) or [])
        self.process_combo = QComboBox()
        self.species_combo = QComboBox()
        self.species_combo.addItems(getattr(self._host, 'coffee_beans_species', []) or [])
        self.varieties_combo = QComboBox()
        self.varieties_combo.setEditable(True)
        self.density_spin = QDoubleSpinBox()
        self.density_spin.setRange(0.0, 1000.0)
        self.density_spin.setDecimals(1)
        self.density_spin.setSuffix(" g/L")
        self.humidity_spin = QDoubleSpinBox()
        self.humidity_spin.setRange(0.0, 30.0)
        self.humidity_spin.setDecimals(1)
        self.humidity_spin.setSuffix(" %")
        self.wa_spin = QDoubleSpinBox()
        self.wa_spin.setRange(0.0, 1.0)
        self.wa_spin.setDecimals(2)
        self.wa_spin.setSingleStep(0.01)
        self.wa_spin.setSuffix(" aw")
        f.addRow(QApplication.translate("tilauscope_sacks", "Category:"), self.category_combo)
        f.addRow(QApplication.translate("tilauscope_sacks", "Process:"), self.process_combo)
        f.addRow(QApplication.translate("tilauscope_sacks", "Species:"), self.species_combo)
        f.addRow(QApplication.translate("tilauscope_sacks", "Varieties:"), self.varieties_combo)
        f.addRow(QApplication.translate("tilauscope_sacks", "Density:"), self.density_spin)
        f.addRow(QApplication.translate("tilauscope_sacks", "Humidity:"), self.humidity_spin)
        f.addRow(QApplication.translate("tilauscope_sacks", "Water activity:"), self.wa_spin)
        zl.addLayout(f)
        v.addWidget(z)
        v.addStretch(1)

        self.species_combo.currentTextChanged.connect(self._refresh_varieties)
        self.category_combo.currentTextChanged.connect(self._refresh_processes)
        self._refresh_varieties(self.species_combo.currentText())
        self._refresh_processes(self.category_combo.currentText())
        return page

    def _pick_type(self, target: _Pill) -> None:
        for p in (self.pill_single, self.pill_blend):
            p.setChecked(p is target)
        self._blend_w.setVisible(self.pill_blend.isChecked())

    def _refresh_varieties(self, species: str) -> None:
        current = self.varieties_combo.currentText()
        self.varieties_combo.clear()
        items = (getattr(self._host, 'coffee_bean_types', {}) or {}).get(species, [])
        self.varieties_combo.addItems(items)
        if current:
            self.varieties_combo.setEditText(current)

    def _refresh_processes(self, category: str) -> None:
        current = self.process_combo.currentText()
        self.process_combo.clear()
        items = (getattr(self._host, 'coffee_processing_methods', {}) or {}).get(category, [])
        self.process_combo.addItems(items)
        if current:
            idx = self.process_combo.findText(current)
            if idx >= 0:
                self.process_combo.setCurrentIndex(idx)

    # ── Page 5 : sensory ──────────────────────────────────────────────────────
    def _build_sensory_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setSpacing(12)
        v.addWidget(self._section(QApplication.translate("tilauscope_sacks", "Sensory & notes"), optional=True))
        z, zl = self._zone()
        zl.addWidget(self._hint(QApplication.translate("tilauscope_sacks",
            "What this coffee should taste like, plus any memo for future you.")))
        f = QFormLayout()
        f.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        f.setHorizontalSpacing(14)
        f.setVerticalSpacing(10)
        self.sca_spin = QDoubleSpinBox()
        self.sca_spin.setRange(0.0, 100.0)
        self.sca_spin.setDecimals(1)
        self.flavour_edit = QLineEdit()
        self.flavour_edit.setPlaceholderText(QApplication.translate("tilauscope_sacks", "e.g. red fruits, floral, honey"))
        self.flavour_edit.setMinimumWidth(340)
        flav_row = QHBoxLayout()
        flav_row.setContentsMargins(0, 0, 0, 0)
        flav_row.setSpacing(8)
        flav_row.addWidget(self.flavour_edit, 1)
        wheel_btn = self._ghost_btn("🎡 " + QApplication.translate("tilauscope_sacks", "Flavors"))
        wheel_btn.setToolTip(QApplication.translate("tilauscope_sacks", "Select flavor notes based on a Flavor Wheel."))
        wheel_btn.clicked.connect(self._open_flavor_wheel)
        flav_row.addWidget(wheel_btn)
        flav_w = QWidget()
        flav_w.setLayout(flav_row)
        flav_w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.tips_edit = QPlainTextEdit()
        self.tips_edit.setPlaceholderText(QApplication.translate("tilauscope_sacks", "Roasting tips / memo"))
        self.tips_edit.setFixedHeight(70)
        f.addRow(QApplication.translate("tilauscope_sacks", "SCA score:"), self.sca_spin)
        f.addRow(QApplication.translate("tilauscope_sacks", "Flavour notes:"), flav_w)
        f.addRow(QApplication.translate("tilauscope_sacks", "Tips / memo:"), self.tips_edit)
        zl.addLayout(f)
        v.addWidget(z)
        v.addStretch(1)
        return page

    def _open_flavor_wheel(self) -> None:
        try:
            from tilauscope.tilau_wheel import FlavorSelectorDialog  # noqa: PLC0415
            dlg = FlavorSelectorDialog(current_notes=self.flavour_edit.text(),
                                       parent=self)
            if dlg.exec():
                self.flavour_edit.setText(dlg.get_notes())
        except Exception:  # noqa: BLE001
            _logd.exception("sack wizard: flavor wheel failed")

    # ── Page 6 : review ───────────────────────────────────────────────────────
    def _review_card(self, title: str, edit_page: int | None,
                     edit_tooltip: str) -> tuple[QFrame, QVBoxLayout]:
        z, zl = self._zone()
        head = QHBoxLayout()
        t = QLabel(title.upper())
        t.setStyleSheet(
            f"color:{_DIM};font-size:10.5px;"
            f"font-weight:800;letter-spacing:2px;")
        head.addWidget(t)
        head.addStretch(1)
        if edit_page is not None:
            edit = self._ghost_btn("✎ " + QApplication.translate("tilauscope_sacks", "Edit"))
            edit.setToolTip(edit_tooltip)
            edit.clicked.connect(
                lambda _=False, p=edit_page: self._edit_from_review(self._resolve_edit_page(p)))
            head.addWidget(edit)
        zl.insertLayout(0, head)
        return z, zl

    def _build_review_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setSpacing(10)

        ess, essl = self._review_card(
            self._page_titles[self._PAGE_ESSENTIALS], self._PAGE_ESSENTIALS,
            QApplication.translate("tilauscope_sacks", "Edit name, origin, year and weight"))
        self.review_head = QLabel("")
        self.review_head.setWordWrap(True)
        self.review_head.setStyleSheet(
            f"color:{THEME['TEXT']};font-size:14px;font-weight:800;")
        self.review_sack = QLabel("")
        self.review_sack.setProperty('variant', 'secondary')
        essl.addWidget(self.review_head)
        essl.addWidget(self.review_sack)
        v.addWidget(ess)

        self._review_cards: dict[int, tuple[QFrame, QLabel]] = {}
        for page_idx, title, tip in (
                (self._PAGE_PROVENANCE, self._page_titles[self._PAGE_PROVENANCE],
                 QApplication.translate("tilauscope_sacks", "Edit farm, supplier and altitude")),
                (self._PAGE_FACTS, self._page_titles[self._PAGE_FACTS],
                 QApplication.translate("tilauscope_sacks", "Edit type, category, process, species, varieties, "
                     "density, humidity")),
                (self._PAGE_SENSORY, QApplication.translate("tilauscope_sacks", "Sensory"),
                 QApplication.translate("tilauscope_sacks", "Edit SCA score, flavour notes and memo"))):
            card, cl = self._review_card(title, page_idx, tip)
            val = QLabel("")
            val.setWordWrap(True)
            val.setStyleSheet(f"color:{THEME['TEXT']};font-size:12.5px;")
            cl.addWidget(val)
            v.addWidget(card)
            self._review_cards[page_idx] = (card, val)

        self.review_warn = QLabel("")
        self.review_warn.setWordWrap(True)
        self.review_warn.setStyleSheet(f"color: {THEME['WARNING']}; font-size: 11px;")
        self.review_warn.hide()
        v.addWidget(self.review_warn)

        v.addStretch(1)
        return page

    def _resolve_edit_page(self, page_idx: int) -> int:
        # in the new-crop flow the year and weight live on the New crop page,
        # not on the mode-choice Essentials page
        if page_idx == self._PAGE_ESSENTIALS and self._mode() == "newcrop":
            return self._PAGE_NEWCROP
        return page_idx

    def _edit_from_review(self, page_idx: int) -> None:
        self._return_to_review = True
        self._history.append(self._PAGE_REVIEW)
        self._goto(page_idx)

    @staticmethod
    def _join(parts: list[str]) -> str:
        return " · ".join(p for p in parts if p) or "—"

    def _refresh_review(self) -> None:
        mode = self._mode()
        src = self._selected_source_bean()
        if mode == "restock" and src is not None:
            added = self.restock_weight_spin.value()
            self.review_head.setText(self._join(
                [src.name, src.country, str(src.crop) if src.crop else ""]))
            self.review_sack.setText(self._sack_line(added) + "   —   " + QApplication.translate("tilauscope_sacks",
                "Stock:") + f" {src.weight_left:.0f} g → {src.weight_left + added:.0f} g")
        else:
            if mode == "newcrop" and src is not None:
                name, country = src.name, src.country
                crop = self.newcrop_crop_spin.value()
                w = self.newcrop_weight_spin.value()
            else:
                name, country = self.name_edit.text().strip(), self.country_combo.currentText()
                crop = self.crop_spin.value()
                w = self.weight_spin.value()
            self.review_head.setText(self._join([name, country, str(crop)]))
            self.review_sack.setText(self._sack_line(w))

        detailed = mode != "restock"
        for card, _val in self._review_cards.values():
            card.setVisible(detailed)
        if detailed:
            self._review_cards[self._PAGE_PROVENANCE][1].setText(self._join([
                self.farm_edit.text().strip(), self.supplier_edit.text().strip(),
                f"{self.altitude_spin.value()} m" if self.altitude_spin.value() else ""]))
            facts_parts = []
            if self.pill_blend.isChecked():
                ratios = [self.bean1_ratio_spin.value(), self.bean2_ratio_spin.value(),
                          self.bean3_ratio_spin.value()]
                shown = "/".join(f"{r:.0f}" for r in ratios if r > 0)
                facts_parts.append(QApplication.translate("tilauscope_sacks", "Blend") + f" {shown}")
            facts_parts += [
                self.category_combo.currentText(),
                self.process_combo.currentText(),
                self.species_combo.currentText(),
                self.varieties_combo.currentText(),
                f"{self.density_spin.value():.0f} g/L" if self.density_spin.value() else "",
                f"{self.humidity_spin.value():.1f} %" if self.humidity_spin.value() else "",
                f"{self.wa_spin.value():.2f} aw" if self.wa_spin.value() else ""]
            facts = self._join(facts_parts)
            if self.pill_blend.isChecked():
                comps = []
                if self.bean2_combo.currentText().strip():
                    comps.append(f"{self.bean2_combo.currentText().strip()} "
                                 f"{self.bean2_ratio_spin.value():.0f} %")
                if self.bean3_combo.currentText().strip():
                    comps.append(f"{self.bean3_combo.currentText().strip()} "
                                 f"{self.bean3_ratio_spin.value():.0f} %")
                if comps:
                    facts += "\n+ " + " · ".join(comps)
            self._review_cards[self._PAGE_FACTS][1].setText(facts)
            self._review_cards[self._PAGE_SENSORY][1].setText(self._join([
                f"SCA {self.sca_spin.value():.1f}" if self.sca_spin.value() else "",
                self.flavour_edit.text().strip()]))

        # AI flow: point out what could not be extracted / still needs a value.
        warn_parts = []
        if self._ai_used:
            missing = []
            if not self.farm_edit.text().strip():
                missing.append(QApplication.translate("tilauscope_sacks", "farm"))
            if not self.altitude_spin.value():
                missing.append(QApplication.translate("tilauscope_sacks", "altitude"))
            if not self.density_spin.value():
                missing.append(QApplication.translate("tilauscope_sacks", "density"))
            if not self.humidity_spin.value():
                missing.append(QApplication.translate("tilauscope_sacks", "humidity"))
            if not self.sca_spin.value():
                missing.append(QApplication.translate("tilauscope_sacks", "SCA score"))
            if missing:
                warn_parts.append(
                    QApplication.translate("tilauscope_sacks", "Not extracted by the AI:") + " " + ", ".join(missing) + ".")
        if mode == "newcrop" and not (self.density_spin.value() and self.humidity_spin.value()):
            warn_parts.append(QApplication.translate("tilauscope_sacks",
                "No density or humidity for this crop. The roast plan will use "
                "the average for this kind of coffee. You can add the values "
                "later from the bean sheet."))
        if mode != "restock":
            w = self.newcrop_weight_spin.value() if mode == "newcrop" else self.weight_spin.value()
            if w <= 0.0:
                warn_parts.append(QApplication.translate("tilauscope_sacks",
                    "Initial weight is 0 g — use the Essentials ✎ Edit if you "
                    "know how much the sack weighs."))
        if warn_parts:
            self.review_warn.setText("⚠ " + " ".join(warn_parts))
            self.review_warn.show()
        else:
            self.review_warn.hide()

    def _sack_line(self, weight: float) -> str:
        sack_id = self.sack_combo.currentText().strip()
        if sack_id:
            return QApplication.translate("tilauscope_sacks", "Sack") + f" {sack_id} · {weight:.0f} g"
        return f"{weight:.0f} g"

    # ── Navigation ────────────────────────────────────────────────────────────
    def _goto(self, page_idx: int) -> None:
        if page_idx == self._PAGE_SACK:
            self._refresh_sack_pool()
        if page_idx == self._PAGE_ESSENTIALS:
            self._refresh_essentials_mode()
        if page_idx == self._PAGE_NEWCROP:
            self._refresh_newcrop()
        if page_idx == self._PAGE_REVIEW:
            self._refresh_review()
        self.stack.setCurrentIndex(page_idx)

        title = self._page_titles.get(page_idx, "").upper()
        flow = self._flow()
        if page_idx == self._PAGE_INTRO:
            self.step_lbl.setText("")
        elif page_idx in flow:
            self.step_lbl.setText(f"{flow.index(page_idx) + 1}/{len(flow)} — {title}")
        else:
            self.step_lbl.setText(title)

        # the New crop shortcut has no start page to go back to
        on_intro = page_idx == self._PAGE_INTRO
        first_step = self._source_bean is not None and page_idx == self._PAGE_NEWCROP
        self.back_btn.setVisible(not on_intro and not first_step)
        self.start_btn.setVisible(on_intro)
        self.skip_btn.setVisible(page_idx == self._PAGE_SACK)
        self.next_btn.setVisible(page_idx not in (self._PAGE_INTRO, self._PAGE_REVIEW))
        self.create_btn.setVisible(page_idx == self._PAGE_REVIEW)

        self._place_annex_windows(page_idx)

    def _place_annex_windows(self, page_idx: int, force: bool = False) -> None:
        """Show or hide the ⚖ and 💧 float windows for *page_idx*."""
        if not force and not self.isVisible():
            return  # no geometry to anchor to yet — showEvent does it
        # ⚖ live scale reading only next to the weight fields
        if page_idx in (self._PAGE_ESSENTIALS, self._PAGE_NEWCROP):
            self._show_scale_window()
        else:
            self._hide_scale_window()
        # 💧 probe reading only next to the water-activity field
        if page_idx == self._PAGE_NEWCROP:
            self._show_aw_window()
        else:
            self._hide_aw_window()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        # the New crop shortcut reaches its page from __init__, before the
        # dialog is sized and moved — the annex windows were placed against a
        # geometry that did not exist yet, so place them again here
        self._place_annex_windows(self.stack.currentIndex(), force=True)

    # ── Annex float windows (⚖ scale, 💧 probe) ──────────────────────────────
    def _annex_pos(self, win: QDialog, offset_y: int) -> tuple[int, int]:
        """Right edge of the wizard, flipped left and clamped to stay on screen."""
        geo = self.geometry()
        w = max(win.width(), win.sizeHint().width())
        h = max(win.height(), win.sizeHint().height())
        x, y = geo.right() + 12, geo.top() + offset_y
        scr = self.screen()
        if scr is not None:
            avail = scr.availableGeometry()
            if x + w > avail.right():
                x = geo.left() - w - 12
            x = max(avail.left(), min(x, avail.right() - w))
            y = max(avail.top(), min(y, avail.bottom() - h))
        return x, y

    # ── Acaia scale capture (same float window as ROAST SETUP) ───────────────
    def _show_scale_window(self) -> None:
        try:
            sm = getattr(self._aw, 'scale_manager', None)
            if sm is None or not sm.is_scale1_configured():
                return
            if self._scale_window is None:
                from tilauscope.roast_properties import _ScaleFloatWindow
                self._scale_window = _ScaleFloatWindow(self)  # type: ignore[arg-type]
                self._scale_was_connected = sm.is_scale1_connected()
                sm.scale1_weight_changed_signal.connect(self._scale_window.update_weight)
                sm.scale1_stable_weight_changed_signal.connect(self._scale_window.update_weight)
                sm.scale1_disconnected_signal.connect(self._scale_window.scale_disconnected)
                if not self._scale_was_connected:
                    sm.connect_scale1_signal.emit(False)
                else:
                    last = sm.get_scale1_last_weight()
                    if last is not None:
                        self._scale_window.update_weight(last)
            self._scale_window.move(*self._annex_pos(self._scale_window, 60))
            self._scale_window.show()
            self._scale_window.raise_()
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _logd.exception('wizard scale window unavailable')

    def _hide_scale_window(self) -> None:
        if self._scale_window is not None and self._scale_window.isVisible():
            self._scale_window.hide()

    def receive_scale_weight(self, weight: float) -> None:
        # _ScaleFloatWindow contract: click on the live reading lands here.
        target = {'new': self.weight_spin,
                  'restock': self.restock_weight_spin,
                  'newcrop': self.newcrop_weight_spin}[self._mode()]
        target.setValue(float(weight))
        self._refresh_essentials_mode()

    def _teardown_scale(self) -> None:
        if self._scale_window is None:
            return
        sm = getattr(self._aw, 'scale_manager', None)
        if sm is not None:
            for _sig, _slot in (
                (sm.scale1_weight_changed_signal, self._scale_window.update_weight),
                (sm.scale1_stable_weight_changed_signal, self._scale_window.update_weight),
                (sm.scale1_disconnected_signal, self._scale_window.scale_disconnected),
            ):
                try:
                    _sig.disconnect(_slot)
                except (TypeError, RuntimeError):
                    pass
            try:
                # only release the scale if the wizard was the one to grab it
                if not self._scale_was_connected:
                    sm.disconnect_scale1_signal.emit()
            except Exception:  # noqa: BLE001  pylint: disable=broad-except
                _logd.exception('wizard scale disconnect failed')
        self._scale_window.close()
        self._scale_window = None

    # ── 💧 AquaGauge capture (same annex window as the zone editor) ──────────
    def _show_aw_window(self) -> None:
        try:
            dev = getattr(self._host, 'bleRoastSeeAGDevice', None)
            if dev is None and getattr(self._aw, 'bleRoastSeeAGDeviceName', None) is None:
                return  # no AquaGauge configured
            if self._aw_win is None:
                from tilauscope.beancave_zone_editors import _AwFloatWindow
                self._aw_win = _AwFloatWindow(self)  # type: ignore[arg-type]
                # the host forwards every probe reading here while we are open
                self._host._aw_capture_cb = self._aw_win.update_value
                if dev is not None:
                    last = getattr(getattr(dev, 'ag', None), 'water_activity_read', 0.0) or 0.0
                    if last > 0:
                        self._aw_win.update_value(last)
                    if not getattr(dev, 'is_connected', False):
                        self._aw_win.set_status(QApplication.translate("tilauscope_sacks", "probe not connected…"))
            # below the ⚖ scale window, which sits at the top of the same edge
            self._aw_win.move(*self._annex_pos(self._aw_win, 220))
            self._aw_win.show()
            self._aw_win.raise_()
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _logd.exception('wizard aw window unavailable')

    def _hide_aw_window(self) -> None:
        if self._aw_win is not None and self._aw_win.isVisible():
            self._aw_win.hide()

    def receive_aw(self, wa: float) -> None:
        # _AwFloatWindow contract: click on the live reading lands here.
        self.nc_wa_spin.setValue(float(wa))

    def _teardown_aw(self) -> None:
        if self._aw_win is None:
            return
        try:
            if getattr(self._host, '_aw_capture_cb', None) is self._aw_win.update_value:
                self._host._aw_capture_cb = None
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _logd.exception('aw capture unregister failed')
        self._aw_win.close()
        self._aw_win = None

    def done(self, result: int) -> None:  # noqa: N802
        self._teardown_scale()
        self._teardown_aw()
        super().done(result)

    def _flow(self) -> list[int]:
        """Ordered steps for the current entry point and mode."""
        if self._source_bean is not None:
            return [self._PAGE_NEWCROP, self._PAGE_SACK, self._PAGE_REVIEW]
        mode = self._mode()
        if mode == "newcrop":
            return [self._PAGE_ESSENTIALS, self._PAGE_NEWCROP,
                    self._PAGE_SACK, self._PAGE_REVIEW]
        if mode == "restock" or self._ai_used:
            # the record already exists (or the AI filled it) — steps 3–5 are
            # for brand-new beans only
            return [self._PAGE_ESSENTIALS, self._PAGE_SACK, self._PAGE_REVIEW]
        return [self._PAGE_ESSENTIALS, self._PAGE_SACK, self._PAGE_PROVENANCE,
                self._PAGE_FACTS, self._PAGE_SENSORY, self._PAGE_REVIEW]

    def _next_of(self, cur: int) -> int:
        if self._return_to_review:
            self._return_to_review = False
            return self._PAGE_REVIEW
        flow = self._flow()
        if cur in flow and flow.index(cur) + 1 < len(flow):
            return flow[flow.index(cur) + 1]
        return self._PAGE_REVIEW

    def _on_next(self) -> None:
        cur = self.stack.currentIndex()
        if cur == self._PAGE_ESSENTIALS and not self._validate_essentials():
            return
        if cur == self._PAGE_ESSENTIALS and self._mode() == "newcrop":
            self._prefill_from_source()
        self._history.append(cur)
        self._goto(self._next_of(cur))

    def _on_skip(self) -> None:
        # Skip = leave without a sack id (first-class outcome).
        self.sack_combo.setEditText("")
        self._on_next()

    def _on_back(self) -> None:
        self._return_to_review = False
        if self._history:
            self._goto(self._history.pop())
        else:
            self._goto(self._PAGE_INTRO)

    def _validate_essentials(self) -> bool:
        if self._mode() == "new" and not self.name_edit.text().strip():
            show_styled_message(self, QApplication.translate("tilauscope_sacks", "New sack"),
                                QApplication.translate("tilauscope_sacks", "Please give the bean a name before continuing."),
                                QMessageBox.Icon.Warning)
            self.name_edit.setFocus()
            return False
        if self._mode() != "new" and self._selected_source_bean() is None:
            show_styled_message(self, QApplication.translate("tilauscope_sacks", "New sack"),
                                QApplication.translate("tilauscope_sacks", "Please pick the catalogue bean this sack "
                                    "belongs to."),
                                QMessageBox.Icon.Warning)
            return False
        return True

    # ── Prefill helpers ───────────────────────────────────────────────────────
    def _apply_bean_to_widgets(self, bean: GreenBean) -> None:
        """Prefill all wizard fields from *bean* (AI result or copied record)."""
        def set_combo(combo: QComboBox, value: str) -> None:
            if not value:
                return
            idx = combo.findText(value)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            elif combo.isEditable():
                combo.setEditText(value)

        self.name_edit.setText(bean.name)
        set_combo(self.country_combo, bean.country)
        if bean.crop:
            self.crop_spin.setValue(bean.crop)
        self.farm_edit.setText(bean.farm)
        self.supplier_edit.setText(bean.supplier)
        set_combo(self.category_combo, bean.category)
        self.altitude_spin.setValue(int(bean.altitude or 0))
        set_combo(self.species_combo, bean.species)
        set_combo(self.process_combo, bean.process)
        set_combo(self.varieties_combo, bean.varieties)
        self.density_spin.setValue(bean.density or 0.0)
        self.humidity_spin.setValue(bean.last_humidity or 0.0)
        self.wa_spin.setValue(bean.water_activity or 0.0)
        self.sca_spin.setValue(bean.sca or 0.0)
        self.flavour_edit.setText(bean.flavour_notes)
        self.tips_edit.setPlainText(bean.tips or "")
        # blend
        self._pick_type(self.pill_blend if bean.is_blend else self.pill_single)
        if bean.is_blend:
            self.bean1_ratio_spin.setValue(bean.bean1_ratio or 0.0)
            set_combo(self.bean2_combo, bean.bean2_name)
            self.bean2_ratio_spin.setValue(bean.bean2_ratio or 0.0)
            set_combo(self.bean3_combo, bean.bean3_name)
            self.bean3_ratio_spin.setValue(bean.bean3_ratio or 0.0)

    def _prefill_from_source(self) -> None:
        """New-crop path: copy the whole source record into pages 3–5 once.

        Density, humidity and water activity are deliberately left empty: they
        are measurements of a lot, not properties of the coffee, and a stale
        value would be indistinguishable from a fresh one in the roast plan.
        """
        src = self._selected_source_bean()
        if src is None or self._prefilled_from is src:
            return
        self._apply_bean_to_widgets(src)
        for spin in (self.density_spin, self.humidity_spin, self.wa_spin,
                     self.nc_density_spin, self.nc_humidity_spin, self.nc_wa_spin):
            spin.setValue(0.0)
        self.nc_supplier_edit.setText(src.supplier)
        self.nc_flavour_edit.setText(src.flavour_notes)
        self.nc_sca_spin.setValue(src.sca or 0.0)
        self._prefilled_from = src

    # ── Create ────────────────────────────────────────────────────────────────
    def _create(self) -> None:
        host = self._host
        try:
            from tilauscope.tilauscope_types import BeanCaveContainer  # noqa: PLC0415
            if host.cave is None:
                host.cave = BeanCaveContainer(green_beans=[], reference_profiles=[])

            mode = self._mode()
            sack_id = self.sack_combo.currentText().strip()
            target_uuid = ""

            if mode == "restock":
                src = self._selected_source_bean()
                if src is None:
                    return
                src.weight_left += self.restock_weight_spin.value()
                if sack_id and sack_id not in (src.sacks or []):
                    src.sacks = list(src.sacks or []) + [sack_id]
                target_uuid = src.uuid
            else:
                bean = self._collect_bean(mode)
                if sack_id:
                    bean.sacks = [sack_id]
                host.cave.green_beans.append(bean)
                if not hasattr(host, 'uuidmap'):
                    host.uuidmap = {}
                host.uuidmap[bean.uuid] = bean
                target_uuid = bean.uuid
                # explicit operator choice: the previous harvest is done
                if mode == "newcrop" and self.nc_retire_chk.isChecked():
                    src = self._selected_source_bean()
                    if src is not None:
                        src.weight_left = 0.0

            if sack_id:
                # drop the label from both available stores (free + printed)
                SackPool.mark_assigned(sack_id)

            host.save_green_beans()
            host.populate_table()
            self._select_row_by_uuid(target_uuid)
            _logd.debug(f"new sack wizard: {mode} saved (sack={sack_id or 'none'})")
            self.accept()
        except Exception as e:  # noqa: BLE001
            _logd.exception("new sack wizard: create failed")
            show_styled_message(self, QApplication.translate("tilauscope_sacks", "Save Error"),
                                QApplication.translate("tilauscope_sacks", "An unexpected error occurred") + f": {e}",
                                QMessageBox.Icon.Warning)

    def _collect_bean(self, mode: str) -> GreenBean:
        src = self._selected_source_bean()
        if mode == "newcrop" and src is not None:
            # dial-ins are tuned on one lot — they do not travel to the next
            base = dataclasses.replace(
                src,
                crop=self.newcrop_crop_spin.value(),
                weight_left=self.newcrop_weight_spin.value(),
                count=0,
                weight=0.0,
                sacks=[],
                dial_ins=[],
                uuid=str(_uuid.uuid4()),
            )
        else:
            base = GreenBean(
                name=self.name_edit.text().strip() or "New Bean",
                country=self.country_combo.currentText(),
                crop=self.crop_spin.value(),
                weight_left=self.weight_spin.value(),
                uuid=str(_uuid.uuid4()),
            )
        # Pages 3–5 always reflect the final values (prefilled for new crop,
        # AI-filled or hand-filled for a new bean).
        base.farm = self.farm_edit.text().strip()
        base.supplier = self.supplier_edit.text().strip()
        base.category = self.category_combo.currentText()
        base.altitude = int(self.altitude_spin.value())
        base.process = self.process_combo.currentText()
        base.species = self.species_combo.currentText()
        base.varieties = self.varieties_combo.currentText()
        base.density = self.density_spin.value()
        base.last_humidity = self.humidity_spin.value()
        base.water_activity = self.wa_spin.value()
        base.sca = self.sca_spin.value()
        base.flavour_notes = self.flavour_edit.text().strip()
        base.tips = self.tips_edit.toPlainText().strip()
        # blend
        base.is_blend = self.pill_blend.isChecked()
        if base.is_blend:
            base.bean1_ratio = self.bean1_ratio_spin.value()
            base.bean2_name = self.bean2_combo.currentText().strip()
            base.bean2_ratio = self.bean2_ratio_spin.value()
            base.bean3_name = self.bean3_combo.currentText().strip()
            base.bean3_ratio = self.bean3_ratio_spin.value()
        else:
            base.bean1_ratio = 100.0
            base.bean2_name = ""
            base.bean2_ratio = 0.0
            base.bean3_name = ""
            base.bean3_ratio = 0.0
        return base

    def _select_row_by_uuid(self, target_uuid: str) -> None:
        if not target_uuid:
            return
        table = self._host.datatable
        for r in range(table.rowCount()):
            anchor = table.item(r, 0)
            if anchor is not None and anchor.data(Qt.ItemDataRole.UserRole) == target_uuid:
                table.selectRow(r)
                break

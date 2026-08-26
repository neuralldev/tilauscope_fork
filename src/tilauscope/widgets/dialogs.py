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

"""Dialogs the roasting window raises that carry no roasting state."""

from __future__ import annotations

from typing import Final

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QApplication, QDialog, QFrame, QHBoxLayout,
                             QLabel, QPushButton, QStyle, QVBoxLayout,
                             QWidget)

from tilauscope.theme_qss import base_qss
from tilauscope.tilauscope_types import _IS_MACOS, THEME


class PlaybackWarningDlg(QDialog):
    """
    Boîte de dialogue de sécurité pour TilauScope.
    Prévient l'utilisateur si des automatismes de playback sont actifs au départ.
    """
    # Constantes de retour pour identifier le choix
    CONTINUE: Final = 1
    CANCEL: Final = 0
    DISABLE_AND_START: Final = 2

    def __init__(self, parent: QWidget, active_modes: list[str]) -> None:
        super().__init__(parent,
                         Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # One sheet per widget: setStyleSheet replaces, it does not
        # merge, so the base has to be concatenated here rather than applied
        # by apply_tilau_theme() and then overwritten on the next line.
        # ground=False — the dialog is translucent and the visible surface is
        # the #PlaybackWarning card below.
        self.setStyleSheet(base_qss(ground=False) + f"""
            QTextEdit     {{ border: none; background: transparent; font-size: 12px; }}
            QLabel#Header {{ font-weight: bold; font-size: 13px; color: {THEME['TEXT']}; }}
        """)
        # ── Outer shell (gives the translucent rounded frame) ──────────────
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setObjectName("PlaybackWarning")
        card.setStyleSheet(f"""
            #PlaybackWarning {{
                background-color : {THEME['BG']};
                border           : 2px solid {THEME['ACCENT']};
                border-radius    : 14px;
            }}
        """)
        outer.addWidget(card)

        root = QVBoxLayout(card)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        # ── Icon + title ───────────────────────────────────────────────────
        title_row = QHBoxLayout()
        title_row.setSpacing(10)

        icon_lbl = QLabel("🫘")
        icon_lbl.setStyleSheet("font-size: 26px;")
        title_lbl = QLabel(QApplication.translate("tilauscope_window", "TilauScope Security"))
        title_lbl.setStyleSheet(f"""
            color       : {THEME['ACCENT']};
            font-size   : 14px;
            font-weight : 800;
            letter-spacing: 1px;
        """)

        title_row.addWidget(icon_lbl)
        title_row.addWidget(title_lbl)
        title_row.addStretch()
        root.addLayout(title_row)
        # ── Separator ──────────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {THEME.get('BORDER', '#3f3f3f')};")
        root.addWidget(sep)

        q_lbl = QLabel()
        q_lbl.setPixmap(self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning).pixmap(48, 48))
        q_lbl.setStyleSheet(f"""
            color       : {THEME['ACCENT']};
            font-size   : 11px;
        """)
        root.addWidget(q_lbl)

        modes_str = ", ".join(active_modes)
        text = (
            f"<b>{QApplication.translate('Message', 'WARNING REPLAY AUTOMATISM ARE ACTIVE')}</b>"
            "<br><br>"
            + QApplication.translate(
                'tilauscope_window',
                'The following features are activated on your background profile '
                'to replay events:')
            + "<br><br>"
            f"<span style='color: #e74c3c;'><b>{modes_str}</b></span><br><br>"
            + QApplication.translate(
                'tilauscope_window',
                'Do you really want to start the roast or review your configuration?')
        )

        label = QLabel(text)
        label.setStyleSheet(f"""
            color       : {THEME['ACCENT']};
            font-size   : 11px;
        """)
        label.setWordWrap(True)
        root.addWidget(label)

        self.result_code = self.CANCEL
        # ── Buttons ────────────────────────────────────────────────────────
        btn_style_primary = f"""
            QPushButton {{
                background-color : {THEME['ACCENT']};
                color            : {THEME['BG']};
                border           : none;
                border-radius    : 6px;
                padding          : 8px 18px;
                font-size        : 11px;
                font-weight      : 700;
            }}
            QPushButton:hover {{
                background-color : {THEME['LAVENDER']};
            }}
            QPushButton:pressed {{
                background-color : {THEME['SURFACE']};
                color            : {THEME['ACCENT']};
                border           : 1px solid {THEME['ACCENT']};
            }}
        """

        # Boutons
        btn_layout = QHBoxLayout()

        self.btn_cancel = QPushButton(QApplication.translate('Button', 'Cancel Roasting'))
        self.btn_cancel.setStyleSheet(btn_style_primary)
        self.btn_disable = QPushButton(QApplication.translate('Button', 'Deactivate all and Roast'))
        self.btn_disable.setStyleSheet(btn_style_primary)
        self.btn_continue = QPushButton(QApplication.translate('Button', 'Continue as is'))
        self.btn_continue.setStyleSheet(btn_style_primary)

        # Gestion de l'ordre des boutons (Native Look)
        if _IS_MACOS: # macOS
            btn_layout.addWidget(self.btn_cancel)
            btn_layout.addStretch()
            btn_layout.addWidget(self.btn_continue)
            btn_layout.addWidget(self.btn_disable)
        else: # Windows / Linux
            btn_layout.addStretch()
            btn_layout.addWidget(self.btn_disable)
            btn_layout.addWidget(self.btn_continue)
            btn_layout.addWidget(self.btn_cancel)

        root.addLayout(btn_layout)

        # Connexions
        self.btn_cancel.clicked.connect(self.do_cancel)
        self.btn_continue.clicked.connect(self.do_continue)
        self.btn_disable.clicked.connect(self.do_disable)

    def do_cancel(self):
        self.result_code = self.CANCEL
        self.reject()

    def do_continue(self):
        self.result_code = self.CONTINUE
        self.accept()

    def do_disable(self):
        self.result_code = self.DISABLE_AND_START
        self.accept()

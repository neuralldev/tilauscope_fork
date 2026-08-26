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

"""Cards that fade in on the alarm sidebar when something fires."""

from __future__ import annotations

from PyQt6.QtCore import QPropertyAnimation, Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from tilauscope.tilauscope_types import THEME


class EventFiredBadge(QFrame):
    """Carte affichée dans AlarmSidebar lors d'un appui sur un bouton EventPanel.

    Style : fond BG du thème, bordure gauche 4 px couleur Artisan, tag EVT,
    fade-in 400 ms identique à TriggeredAlarmBadge.
    """

    def __init__(self, label: str, command: str, timestamp: str, color: str, parent=None):
        super().__init__(parent)
        self.setFixedWidth(200)
        self.setMinimumHeight(60)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME['BG']};
                border: 1px solid {color}33;
                border-left: 4px solid {color};
                border-radius: 8px;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(2)

        # Ligne header : tag EVT + timestamp
        header_row = QHBoxLayout()
        tag = QLabel("EVT")
        tag.setStyleSheet(f"color: {color}; font-weight: 900; font-size: 9px; border: none; letter-spacing: 1px;")
        ts_lbl = QLabel(timestamp)
        ts_lbl.setStyleSheet(f"color: {THEME['SURFACE2']}; font-size: 9px; border: none;")
        ts_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header_row.addWidget(tag)
        header_row.addStretch(1)
        header_row.addWidget(ts_lbl)
        layout.addLayout(header_row)

        # Label du bouton
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {color}; font-weight: 700; font-size: 11px; border: none;")
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        # Commande (si disponible)
        if command:
            cmd_lbl = QLabel(command)
            cmd_lbl.setStyleSheet(f"color: {THEME['OVERLAY0']}; font-size: 9px; border: none;")
            cmd_lbl.setWordWrap(True)
            layout.addWidget(cmd_lbl)

        # Fade-in 400 ms
        self.setWindowOpacity(0.0)
        self._anim = QPropertyAnimation(self, b"windowOpacity")
        self._anim.setDuration(400)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()

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

"""One block of the roast phase box: a name, a target and how far along it is."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QFrame, QLabel, QProgressBar, QSizePolicy,
                             QVBoxLayout)

from tilauscope.tilauscope_types import THEME


class PhaseWidget(QFrame):
    def __init__(self, alias, name, color, theme, subtitle=None):
        super().__init__()
        self.theme = theme
        self.name = name
        self.alias = alias
        self.phase_color = color  # Store the specific phase color (blue, yellow, or pink)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(2, 2, 2, 2)
        self.layout.setSpacing(0)
        if subtitle is not None:
            name += "<br>"+subtitle
        self.lbl = QLabel(name)
        self.lbl.setWordWrap(True)
        self.lbl.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.lbl.setAlignment(Qt.AlignmentFlag.AlignCenter) # Align to bottom
        self.lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.lbl.setStyleSheet(f"color: {THEME['SUBTEXT']}; font-size: 12px; font-weight: 800; border: none;")
        self.lbl.setAutoFillBackground(True)

        self.stats = QLabel("00:00 (0%)")
        self.stats.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stats.setStyleSheet(f"color: {THEME['OVERLAY0']}; font-size: 13px; font-family: 'JetBrains Mono'; border: none;")

        self.bar = QProgressBar()
        self.bar.setFixedHeight(4)
        self.bar.setTextVisible(False)
        self.bar.setStyleSheet(f"QProgressBar {{ background: {THEME['BG']}; border: none; border-radius: 3px; }} QProgressBar::chunk {{ background: {color}; border-radius: 3px; }}")

        self.layout.addWidget(self.lbl)
        self.layout.addWidget(self.stats)
        self.layout.addSpacing(10)
        self.layout.addWidget(self.bar)
        self.setStyleSheet("border: none; background: transparent;")
        self.set_progress(0)

    def update_subtitle(self, subtitle):
        name = self.name +f"<br>{subtitle}" if subtitle is not None else ""
        self.lbl.setText(name)

    def set_active(self, active=True):
        if active:
            # ACTIVE: Highlight with the specific phase color border (Yellow for Maillard, etc.)
            self.lbl.setStyleSheet("color: white; font-size: 12px; font-weight: 900; border: none;")
            self.stats.setStyleSheet("color: white; font-size: 13px; font-family: 'JetBrains Mono'; font-weight: bold; border: none;")
            self.setStyleSheet(f"""
                PhaseWidget {{
                    background: {self.theme['BG']};
                    border-radius: 10px;
                    border: 2px solid {self.phase_color};
                }}
            """)
        else:
            # INACTIVE: Normal gray/white style, no border
            self.lbl.setStyleSheet(f"color: {THEME['OVERLAY0']}; font-size: 12px; border: none;")
            self.stats.setStyleSheet("color: #475569; font-size: 13px; border: none;font-size: 13px; font-family: 'JetBrains Mono'; ")
            self.setStyleSheet("PhaseWidget { background: transparent; border: none; }")

    def update_stats(self, seconds, total_seconds):
            """Updates the timer and percentage label."""
            m, s = divmod(int(seconds), 60)
            percent = min(100, max(0, int((seconds / total_seconds * 100)))) if total_seconds > 0 else 0
#            percent = int((seconds / total_seconds * 100)) if total_seconds > 0 else 0
            new_text = f"{m:02d}:{s:02d} ({percent}%)"
            if self.stats.text() != new_text: # Only update if string changed
                self.stats.setText(new_text)

    def set_progress(self, percent):
        """Sets the progress bar value (0-100)."""
        self.bar.setValue(min(100, max(0, int(percent))))

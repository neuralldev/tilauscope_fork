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

"""The pieces TilauScope's settings windows are built from.

TilauScope Config and Devices draw the same rounded card, tab strip, section
headings and device rows. Both take them from here, so the two windows cannot
drift apart one restyle at a time.
"""

from __future__ import annotations

from typing import Final

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, Qt, pyqtSlot
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import (QFrame, QLabel, QListView, QPushButton, QScrollArea,
                             QVBoxLayout, QWidget)

from tilauscope.theme_qss import styled_popup_view, tooltip_qss
from tilauscope.tilauscope_types import THEME

#: Side of the square icon buttons (🗑) — matches the height of a combo row.
ICON_BUTTON_SIZE: Final[int] = 34


# What a settings window needs on top of theme_qss.base_qss(): only rules that
# differ from the base, each with its own reason. See wiki/Theme-QSS-Spec.md.
def config_dialog_qss() -> str:
    return f"""
        /* combobox-popup is behaviour, not decoration: without it Qt shows a
           native popup menu on macOS that no stylesheet can reach. */
        QComboBox {{ combobox-popup: 1; }}
        QComboBox::drop-down {{ border: none; }}

        /* Inline cell editor: Qt paints it over the cell without clearing it,
           so an unstyled (transparent) editor shows the old text underneath. */
        QTableWidget QLineEdit, QTableWidget QAbstractItemView QLineEdit {{
            background: {THEME['BG']};
            color: {THEME['TEXT']};
            border: 1px solid {THEME['ACCENT']};
            border-radius: 3px;
            padding: 1px 3px;
            margin: 0px;
            font-size: 12px;
            selection-background-color: {THEME['ACCENT']};
            selection-color: {THEME['BG']};
        }}

        /* Section headings are set as spaced small caps throughout these
           windows — the tab bar and the group boxes have to agree. */
        QGroupBox {{
            color: {THEME['SUBTEXT']};
            font-size: 11px;
            font-weight: bold;
            letter-spacing: 1.5px;
            padding-top: 6px;
        }}
        QGroupBox::title {{ subcontrol-position: top left; padding: 0 6px; }}

        /* Save / Cancel close the window — deliberately larger than the
           inline action buttons inside the tabs. */
        QPushButton#footerBtn {{
            border-radius: 8px;
            font-size: 13px;
            padding: 9px 24px;
        }}

        /* A dense settings window: the 12px base scrollbar eats the width the
           device rows need. */
        QScrollBar:vertical {{
            background: {THEME['SURFACE']};
            width: 6px;
            border-radius: 3px;
        }}
        QScrollBar::handle:vertical {{
            background: {THEME['BORDER']};
            border-radius: 3px;
        }}
    """


def config_tabs_qss() -> str:
    return f"""
        QTabWidget {{ background: transparent; }}
        QTabWidget::pane {{
            border: none;
            background: transparent;
            margin-top: 0px;
        }}
        QTabWidget > QWidget {{ background: transparent; }}
        QTabBar {{ background: {THEME['BG']}; border: none; }}
        QTabBar::tab {{
            background: {THEME['BG']};
            color: {THEME['SUBTEXT']};
            font-size: 11px;
            font-weight: bold;
            letter-spacing: 1px;
            padding: 8px 18px;
            border: none;
            border-bottom: 2px solid transparent;
            margin-right: 2px;
        }}
        QTabBar::tab:selected {{
            background: {THEME['BG']};
            color: {THEME['ACCENT']};
            border-bottom: 2px solid {THEME['ACCENT']};
        }}
        QTabBar::tab:hover:!selected {{
            background: {THEME['BG']};
            color: {THEME['TEXT']};
            border-bottom: 2px solid {THEME['BORDER']};
        }}
    """


def config_card() -> tuple[QFrame, QVBoxLayout]:
    """The rounded accent-bordered card a translucent settings window paints."""
    card = QFrame()
    card.setObjectName('configCard')
    card.setStyleSheet(f"""
        QFrame#configCard {{
            background-color: {THEME['BG']};
            border: 2px solid {THEME['ACCENT']};
            border-radius: 20px;
        }}
    """)
    layout = QVBoxLayout(card)
    layout.setContentsMargins(28, 22, 28, 20)
    layout.setSpacing(12)
    return card, layout


def dialog_title(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color: {THEME['ACCENT']}; font-size: 15px; font-weight: 800;"
        f"letter-spacing: 3px;"
    )
    return lbl


def close_button() -> QPushButton:
    btn = QPushButton('✕')
    btn.setFixedSize(30, 30)
    btn.setProperty('variant', 'icon')   # fixed size: no base padding
    btn.setStyleSheet(f"""
        QPushButton {{
            background: {THEME['BORDER']};
            color: {THEME['CRITICAL']};
            border-radius: 15px;
            border: 1px solid {THEME['CRITICAL']};
            font-weight: bold;
            font-size: 13px;
        }}
        QPushButton:hover {{
            background: {THEME['CRITICAL']};
            color: {THEME['BG']};
        }}
    """)
    return btn


def styled_combo_view() -> QListView:
    """Fresh Mocha-styled popup view for a device QComboBox.

    The combo can shrink (Ignored policy), but the popup must stay wide enough
    to show the full BLE UUID/MAC of each detected device.
    """
    return styled_popup_view(min_width=360)


def trash_button_qss() -> str:
    """Fixed square icon button — forgets (unassigns or removes) a device."""
    return f"""
        QPushButton {{
            background-color: transparent;
            color: {THEME['SUBTEXT']};
            border: 1px solid {THEME['BORDER']};
            border-radius: 6px;
            font-size: 13px;
            padding: 0px;
            min-width: {ICON_BUTTON_SIZE}px;
            max-width: {ICON_BUTTON_SIZE}px;
            min-height: {ICON_BUTTON_SIZE}px;
            max-height: {ICON_BUTTON_SIZE}px;
        }}
        QPushButton:hover {{
            border-color: {THEME['CRITICAL']};
            color: {THEME['CRITICAL']};
        }}
    """ + tooltip_qss()


def separator() -> QFrame:
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.HLine)
    sep.setStyleSheet(
        f"color: {THEME['BORDER']}; background: {THEME['BORDER']}; max-height:1px;"
    )
    return sep


def section_label(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setStyleSheet(
        f"color: {THEME['ACCENT']}; font-size: 11px; font-weight: bold;"
        f"letter-spacing: 2px; margin-top: 4px;"
    )
    return lbl


def field_label(text: str, width: int = 150) -> QLabel:
    lbl = QLabel(text)
    lbl.setProperty('variant', 'secondary')
    lbl.setMinimumWidth(width)
    return lbl


def scrollable(parent: QWidget) -> QScrollArea:
    """Wrap a tab widget's root in a scrollable area with a QVBoxLayout content."""
    scroll = QScrollArea(parent)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    # content only scrolls vertically — never show a horizontal bar
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    content = QWidget()
    lay = QVBoxLayout(content)
    lay.setContentsMargins(0, 12, 0, 12)
    lay.setSpacing(12)
    scroll.setWidget(content)

    tab_layout = QVBoxLayout(parent)
    tab_layout.setContentsMargins(0, 0, 0, 0)
    tab_layout.addWidget(scroll)

    return scroll


def toolbar_button(text: str, accent: str | None = None) -> QPushButton:
    """A command in a window's top bar — the alarm editor's look, shared with Devices."""
    button = QPushButton(text)
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    colour = accent or THEME['TEXT']
    button.setStyleSheet(
        f"QPushButton {{ background: {THEME['SURFACE']}; color: {colour};"
        f"border: 1px solid {THEME['BORDER']}; border-radius: 7px;"
        f"padding: 5px 11px; font-size: 11px; }}"
        f"QPushButton:hover {{ border-color: {colour}; }}"
        f"QPushButton:disabled {{ color: {THEME['OVERLAY0']}; border-color: {THEME['BORDER']}; }}")
    return button


class QCollapsibleWidget(QWidget):
    """
    A titled section that can be collapsed/expanded via a toggle button.
    Content is placed in self.content_widget (QWidget with a QVBoxLayout).

    Usage:
        section = QCollapsibleWidget("AirWave PID", collapsed=True)
        section.content_layout.addWidget(some_table)
        parent_layout.addWidget(section)
    """

    def __init__(self, title: str, collapsed: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._collapsed = collapsed

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Toggle button ────────────────────────────────────────────────
        self._toggle_btn = QPushButton()
        self._toggle_btn.setCheckable(True)
        self._toggle_btn.setChecked(not collapsed)
        self._toggle_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._toggle_btn.setStyleSheet(f"""
            QPushButton {{
                background: {THEME['SURFACE']};
                color: {THEME['SUBTEXT']};
                border: 1px solid {THEME['BORDER']};
                border-radius: 6px;
                font-size: 11px;
                font-weight: bold;
                letter-spacing: 1px;
                padding: 6px 12px;
                text-align: left;
            }}
            QPushButton:hover {{
                border-color: {THEME['ACCENT']};
                color: {THEME['ACCENT']};
            }}
            QPushButton:checked {{
                color: {THEME['ACCENT']};
                border-color: {THEME['ACCENT']};
            }}
        """)
        self._set_toggle_label(title)
        self._title = title
        self._toggle_btn.toggled.connect(self._on_toggle)
        root.addWidget(self._toggle_btn)

        # ── Content area ─────────────────────────────────────────────────
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(0, 8, 0, 4)
        self.content_layout.setSpacing(8)

        # Animated max-height
        self._anim = QPropertyAnimation(self.content_widget, b"maximumHeight")
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutQuad)

        self.content_widget.setMaximumHeight(0 if collapsed else 16_777_215)
        self.content_widget.setVisible(not collapsed)
        root.addWidget(self.content_widget)

    def _set_toggle_label(self, title: str) -> None:
        arrow = "▶" if self._collapsed else "▼"
        self._toggle_btn.setText(f" {arrow}  {title.upper()}")

    @pyqtSlot(bool)
    def _on_toggle(self, checked: bool) -> None:
        self._collapsed = not checked
        self._set_toggle_label(self._title)

        # Disconnect stale finished callbacks before configuring new ones
        try:
            self._anim.finished.disconnect()
        except TypeError:
            pass

        if checked:
            # Expand: make visible at height 0, animate to natural height
            self.content_widget.setVisible(True)
            self.content_widget.setMaximumHeight(0)
            natural = self.content_widget.sizeHint().height()
            self._anim.setStartValue(0)
            self._anim.setEndValue(max(natural, 20))
            self._anim.finished.connect(
                lambda: self.content_widget.setMaximumHeight(16_777_215)
            )
        else:
            # Collapse: animate to 0, then hide
            current = self.content_widget.height()
            self._anim.setStartValue(current)
            self._anim.setEndValue(0)
            self._anim.finished.connect(
                lambda: self.content_widget.setVisible(False)
            )
        self._anim.start()
